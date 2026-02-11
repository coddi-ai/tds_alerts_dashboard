"""
S3 Data Uploader Script

This script uploads data to the S3 bucket, checking if files already exist
before uploading to avoid unnecessary transfers.
"""

import os
import boto3
from pathlib import Path
from typing import Optional, List
from tqdm import tqdm
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

from src.utils.logger import get_logger

logger = get_logger(__name__)


class S3Uploader:
    """Uploads data from local storage to S3."""
    
    def __init__(
        self, 
        bucket_name: str,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region_name: str = "us-east-1"
    ):
        """
        Initialize S3 uploader.
        
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
    
    def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3.
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            logger.debug(f"File exists in S3: {s3_key}")
            return True
        except ClientError as e:
            # If error code is 404, file doesn't exist
            if e.response['Error']['Code'] == '404':
                logger.debug(f"File does not exist in S3: {s3_key}")
                return False
            else:
                # Other error occurred
                logger.error(f"Error checking file existence: {e}")
                raise
    
    def upload_file(
        self, 
        local_path: Path, 
        s3_key: str,
        skip_if_exists: bool = True,
        extra_args: Optional[dict] = None
    ) -> bool:
        """
        Upload a single file to S3.
        
        Args:
            local_path: Local file path
            s3_key: S3 object key (destination path)
            skip_if_exists: If True, skip upload if file already exists
            extra_args: Additional arguments for upload (e.g., ContentType, Metadata)
            
        Returns:
            True if uploaded, False if skipped or failed
        """
        try:
            # Check if file exists locally
            if not local_path.exists():
                logger.error(f"Local file not found: {local_path}")
                return False
            
            # Check if file already exists in S3
            if skip_if_exists and self.file_exists(s3_key):
                logger.debug(f"Skipping upload (already exists): {s3_key}")
                return False
            
            # Upload the file
            self.s3_client.upload_file(
                str(local_path),
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            logger.debug(f"Uploaded: {local_path} -> s3://{self.bucket_name}/{s3_key}")
            return True
            
        except NoCredentialsError:
            logger.error("AWS credentials not found. Please configure your credentials.")
            raise
        except ClientError as e:
            logger.error(f"Error uploading {local_path}: {e}")
            return False
    
    def upload_folder(
        self,
        local_dir: Path,
        s3_prefix: str,
        skip_if_exists: bool = True,
        file_patterns: Optional[List[str]] = None
    ) -> dict:
        """
        Upload all files from a local directory to an S3 folder.
        
        Args:
            local_dir: Local directory path
            s3_prefix: S3 prefix (folder path) where files will be uploaded
            skip_if_exists: If True, skip files that already exist in S3
            file_patterns: List of glob patterns to match files (e.g., ['*.csv', '*.json'])
                          If None, uploads all files
            
        Returns:
            Dictionary with upload statistics
        """
        logger.info(f"Starting upload to s3://{self.bucket_name}/{s3_prefix}")
        logger.info(f"Source: {local_dir}")
        
        # Check if local directory exists
        if not local_dir.exists():
            logger.error(f"Local directory not found: {local_dir}")
            return {"total": 0, "uploaded": 0, "skipped": 0, "failed": 0}
        
        # Get list of files to upload
        files_to_upload = []
        
        if file_patterns:
            for pattern in file_patterns:
                files_to_upload.extend(local_dir.rglob(pattern))
        else:
            files_to_upload = [f for f in local_dir.rglob('*') if f.is_file()]
        
        if not files_to_upload:
            logger.warning(f"No files found in {local_dir}")
            return {"total": 0, "uploaded": 0, "skipped": 0, "failed": 0}
        
        logger.info(f"Found {len(files_to_upload)} files to process")
        
        # Upload each file
        uploaded_count = 0
        skipped_count = 0
        failed_count = 0
        
        for local_path in tqdm(files_to_upload, desc="Uploading files"):
            # Create S3 key preserving folder structure
            relative_path = local_path.relative_to(local_dir)
            s3_key = f"{s3_prefix.rstrip('/')}/{relative_path.as_posix()}"
            
            result = self.upload_file(
                local_path,
                s3_key,
                skip_if_exists=skip_if_exists
            )
            
            if result:
                uploaded_count += 1
            elif skip_if_exists and self.file_exists(s3_key):
                skipped_count += 1
            else:
                failed_count += 1
        
        stats = {
            "total": len(files_to_upload),
            "uploaded": uploaded_count,
            "skipped": skipped_count,
            "failed": failed_count
        }
        
        logger.info(f"Upload complete: {uploaded_count} uploaded, {skipped_count} skipped, {failed_count} failed")
        
        return stats
    
    def sync_folder(
        self,
        local_dir: Path,
        s3_prefix: str,
        file_patterns: Optional[List[str]] = None
    ) -> dict:
        """
        Sync local folder to S3 (upload only new/changed files).
        
        Args:
            local_dir: Local directory path
            s3_prefix: S3 prefix (folder path)
            file_patterns: List of glob patterns to match files
            
        Returns:
            Dictionary with sync statistics
        """
        logger.info(f"Syncing {local_dir} to s3://{self.bucket_name}/{s3_prefix}")
        return self.upload_folder(
            local_dir=local_dir,
            s3_prefix=s3_prefix,
            skip_if_exists=True,
            file_patterns=file_patterns
        )


def main():
    """Main function to upload data to S3."""
    
    # Load environment variables from .env file
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / ".env")
    
    # Configuration from .env file
    BUCKET_NAME = os.getenv("BUCKET_NAME")
    ACCESS_KEY = os.getenv("ACCESS_KEY")
    SECRET_KEY = os.getenv("SECRET_KEY")
    S3_PREFIX = "MultiTechnique Alerts/"
    
    if not BUCKET_NAME:
        raise ValueError("BUCKET_NAME not found in .env file")
    if not ACCESS_KEY or not SECRET_KEY:
        raise ValueError("ACCESS_KEY and SECRET_KEY not found in .env file")
    
    local_data_dir = project_root / "data" / "alerts"
    
    logger.info("=" * 60)
    logger.info("S3 Data Upload Script")
    logger.info("=" * 60)
    
    try:
        # Initialize uploader with credentials from .env file
        uploader = S3Uploader(
            bucket_name=BUCKET_NAME,
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY
        )
        
        # Upload the folder (only new files)
        # This will skip files that already exist in S3
        stats = uploader.upload_folder(
            local_dir=local_data_dir,
            s3_prefix=S3_PREFIX,
            skip_if_exists=True,
            file_patterns=['*.csv', '*.json']  # Only upload CSV and JSON files
        )
        
        logger.info("=" * 60)
        logger.info(f"Total files: {stats['total']}")
        logger.info(f"Uploaded: {stats['uploaded']}")
        logger.info(f"Skipped (already exist): {stats['skipped']}")
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
