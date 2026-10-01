"""
S3 Data Downloader Script

This script downloads data from the S3 bucket folder 'MultiTechnique Alerts/' 
to the local data folder.
"""

import os
import boto3
from pathlib import Path
from typing import Optional
from tqdm import tqdm
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

from src.utils.logger import get_logger

logger = get_logger(__name__)


class S3Downloader:
    """Downloads data from S3 to local storage."""
    
    def __init__(
        self, 
        bucket_name: str,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region_name: str = "us-east-1"
    ):
        """
        Initialize S3 downloader.
        
        Args:
            bucket_name: Name of the S3 bucket
            aws_access_key_id: AWS access key (if None, will use default credentials)
            aws_secret_access_key: AWS secret key (if None, will use default credentials)
            region_name: AWS region name
        """
        self.bucket_name = bucket_name
        
        # Initialize S3 client
        if aws_access_key_id and aws_secret_access_key:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region_name
            )
        else:
            # Use default credentials from environment or ~/.aws/credentials
            self.s3_client = boto3.client('s3', region_name=region_name)
    
    def list_objects(self, prefix: str) -> list:
        """
        List all objects in S3 bucket with given prefix.

        Args:
            prefix: S3 prefix (folder path)

        Returns:
            List of dicts with 'Key' and 'Size' for each object
        """
        try:
            objects = []
            paginator = self.s3_client.get_paginator('list_objects_v2')

            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Skip folders (objects ending with /)
                        if not obj['Key'].endswith('/'):
                            objects.append({'Key': obj['Key'], 'Size': obj['Size']})

            logger.info(f"Found {len(objects)} objects with prefix '{prefix}'")
            return objects

        except NoCredentialsError:
            logger.error("AWS credentials not found. Please configure your credentials.")
            raise
        except ClientError as e:
            logger.error(f"Error listing objects: {e}")
            raise
    
    def download_file(self, s3_key: str, local_path: Path) -> bool:
        """
        Download a single file from S3.
        
        Args:
            s3_key: S3 object key
            local_path: Local file path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert to absolute path and handle Windows long paths
            local_path = local_path.resolve()
            
            # Create parent directories if they don't exist
            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error(f"Failed to create directory {local_path.parent}: {e}")
                return False
            
            # Verify the directory exists
            if not local_path.parent.exists():
                logger.error(f"Directory does not exist after creation: {local_path.parent}")
                return False
            
            # Convert to string, use extended path for Windows if path is long
            local_path_str = str(local_path)
            if os.name == 'nt' and len(local_path_str) > 200:
                # Use Windows extended-length path syntax for long paths
                if not local_path_str.startswith('\\\\?\\'):
                    local_path_str = '\\\\?\\' + local_path_str
            
            # Download the file
            self.s3_client.download_file(
                self.bucket_name, 
                s3_key, 
                local_path_str
            )
            
            logger.debug(f"Downloaded: {s3_key} -> {local_path}")
            return True
            
        except ClientError as e:
            logger.error(f"Error downloading {s3_key}: {e}")
            return False
        except OSError as e:
            logger.error(f"OS error downloading {s3_key} to {local_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error downloading {s3_key}: {e}")
            return False
    
    def download_folder(
        self,
        s3_prefix: str,
        local_dir: Path,
        preserve_structure: bool = True
    ) -> dict:
        """
        Sync all files from an S3 folder to local directory, based on file size.

        Downloads new files, re-downloads files whose size differs from the
        local copy, skips files whose size matches, and deletes local files
        that no longer have a corresponding S3 object.

        Args:
            s3_prefix: S3 prefix (folder path)
            local_dir: Local directory path
            preserve_structure: If True, preserves the folder structure from S3

        Returns:
            Dictionary with sync statistics
        """
        logger.info(f"Starting sync from s3://{self.bucket_name}/{s3_prefix}")
        logger.info(f"Destination: {local_dir}")

        # Get list of objects (with sizes)
        objects = self.list_objects(s3_prefix)

        if not objects:
            logger.warning(f"No objects found with prefix '{s3_prefix}'")
            return {"total": 0, "downloaded": 0, "skipped": 0, "deleted": 0, "failed": 0}

        local_dir.mkdir(parents=True, exist_ok=True)

        downloaded_count = 0
        skipped_count = 0
        failed_count = 0
        remote_local_paths = set()

        for obj in tqdm(objects, desc="Syncing files"):
            s3_key = obj['Key']
            s3_size = obj['Size']

            if preserve_structure:
                # Remove the S3 prefix but keep the nested folder structure
                relative_path = s3_key.replace(s3_prefix, '', 1).lstrip('/')
            else:
                # Flatten the structure (extract just the filename)
                relative_path = os.path.basename(s3_key)

            local_path = local_dir / relative_path
            remote_local_paths.add(local_path.resolve())

            needs_download = True
            if local_path.exists():
                if local_path.stat().st_size == s3_size:
                    needs_download = False

            if needs_download:
                if self.download_file(s3_key, local_path):
                    downloaded_count += 1
                else:
                    failed_count += 1
            else:
                skipped_count += 1

        # Delete local files that no longer exist in S3
        deleted_count = 0
        if local_dir.exists():
            for local_file in local_dir.rglob('*'):
                if local_file.is_file() and local_file.resolve() not in remote_local_paths:
                    try:
                        local_file.unlink()
                        deleted_count += 1
                        logger.debug(f"Deleted stale local file: {local_file}")
                    except OSError as e:
                        logger.error(f"Failed to delete {local_file}: {e}")

        stats = {
            "total": len(objects),
            "downloaded": downloaded_count,
            "skipped": skipped_count,
            "deleted": deleted_count,
            "failed": failed_count
        }

        logger.info(
            f"Sync complete: {downloaded_count} downloaded, "
            f"{skipped_count} skipped, {deleted_count} deleted"
        )
        if failed_count > 0:
            logger.warning(f"{failed_count} files failed to download")

        return stats


def main():
    """Main function to download MultiTechnique Alerts data."""
    
    # Load environment variables from .env file
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / ".env")
    
    # Configuration from .env file
    BUCKET_NAME = os.getenv("BUCKET_NAME")
    ACCESS_KEY = os.getenv("ACCESS_KEY")
    SECRET_KEY = os.getenv("SECRET_KEY")
    STAGE_NAME = os.getenv("STAGE_NAME") # Only defined when deployed to the cloud
    S3_PREFIX = "MultiTechnique Alerts/"
    
    if not BUCKET_NAME:
        raise ValueError("BUCKET_NAME not found in .env file")
    if not STAGE_NAME and (not ACCESS_KEY or not SECRET_KEY):
        raise ValueError("ACCESS_KEY and SECRET_KEY not found in .env file")
    
    local_data_dir = project_root / "data"
    
    logger.info("=" * 60)
    logger.info("S3 Data Download Script")
    logger.info("=" * 60)
    print("Download into:", local_data_dir)

    
    try:
        # Initialize downloader with credentials from .env file
        downloader = S3Downloader(
            bucket_name=BUCKET_NAME,
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY
        )
        
        # Download the folder
        # preserve_structure=True will keep nested folders but remove S3 prefix
        # preserve_structure=False will flatten all files to data/ directory
        stats = downloader.download_folder(
            s3_prefix=S3_PREFIX,
            local_dir=local_data_dir,
            preserve_structure=True
        )
        
        print("Files in /app/data after sync:", list(local_data_dir.iterdir()))
        logger.info("=" * 60)
        logger.info(f"Total files in S3: {stats['total']}")
        logger.info(f"Downloaded: {stats['downloaded']}")
        logger.info(f"Skipped (unchanged): {stats['skipped']}")
        logger.info(f"Deleted (stale local files): {stats['deleted']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info("=" * 60)
        
    except NoCredentialsError:
        logger.error(
            "AWS credentials not found. Please configure your credentials using one of:\n"
            "1. Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY\n"
            "2. AWS credentials file: ~/.aws/credentials\n"
            "3. IAM role (if running on EC2)"
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise


if __name__ == "__main__":
    main()
