"""
Script to download data from S3 based on URI lists.

This script downloads files from S3 and organizes them in a local directory structure
based on the technique, layer, and client information contained in the URIs.
"""

import os
import boto3
import pandas as pd
import s3fs
from pathlib import Path
from botocore.exceptions import NoCredentialsError, PartialCredentialsError


# S3 Configuration - Update these with your credentials
BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'your-bucket-name')
ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID', 'your-access-key')
SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', 'your-secret-key')

# Base data directory
BASE_DATA_DIR = Path(__file__).parent.parent.parent / 'data'


def read_from_s3(file_path, bucket_name=BUCKET_NAME):
    """
    Read a file from S3 as a pandas DataFrame.
    
    Args:
        file_path (str): Path to the file in S3 bucket
        bucket_name (str): Name of the S3 bucket
        
    Returns:
        pd.DataFrame: DataFrame containing the file data, or None if failed
    """
    ext = file_path.split('.')[-1].lower()
    
    try:
        if ext == 'parquet':
            fs = s3fs.S3FileSystem(key=ACCESS_KEY, secret=SECRET_KEY)
            s3_uri = f"s3://{bucket_name}/{file_path}"
            with fs.open(s3_uri, "rb") as f:
                df = pd.read_parquet(f)
                print(f"File '{file_path}' successfully read from '{bucket_name}'.")
                return df
        else:
            s3_client = boto3.client('s3', 
                                   aws_access_key_id=ACCESS_KEY,
                                   aws_secret_access_key=SECRET_KEY)
            
            # Read the file
            obj = s3_client.get_object(Bucket=bucket_name, Key=file_path)
            df = pd.read_csv(obj['Body'])
            print(f"File '{file_path}' successfully read from '{bucket_name}'.")
            return df
            
    except FileNotFoundError:
        print(f"ERROR: The file '{file_path}' was not found.")
        return None
    except NoCredentialsError:
        print("ERROR: Credentials not available.")
        return None
    except PartialCredentialsError:
        print("ERROR: Incomplete credentials provided.")
        return None
    except Exception as e:
        print(f"ERROR: Failed to read '{file_path}': {str(e)}")
        return None


def parse_uri(uri):
    """
    Parse S3 URI to extract technique, layer, client, and filename.
    
    Expected format: FOLDER/{TECHNIQUE}/{LAYER}/{CLIENT}/{FILENAME.EXTENSION}
    
    Args:
        uri (str): S3 URI path
        
    Returns:
        tuple: (technique, layer, client, filename) or (None, None, None, None) if invalid
    """
    parts = uri.split('/')
    
    if len(parts) < 5:
        print(f"WARNING: Invalid URI format: {uri}")
        return None, None, None, None
    
    # Extract components from URI
    # FOLDER/{TECHNIQUE}/{LAYER}/{CLIENT}/{FILENAME.EXTENSION}
    technique = parts[1]
    layer = parts[2]
    client = parts[3]
    filename = parts[4]
    
    return technique, layer, client, filename


def save_dataframe_locally(df, technique, layer, client, filename):
    """
    Save a DataFrame to the local directory structure.
    
    Args:
        df (pd.DataFrame): DataFrame to save
        technique (str): Technique name
        layer (str): Layer name (e.g., 'golden', 'silver')
        client (str): Client name
        filename (str): File name with extension
        
    Returns:
        bool: True if saved successfully, False otherwise
    """
    # Create directory structure: data/{TECHNIQUE}/{LAYER}/{CLIENT}/
    target_dir = BASE_DATA_DIR / technique / layer / client
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Full path to the target file
    target_path = target_dir / filename
    
    # Determine file extension
    ext = filename.split('.')[-1].lower()
    
    try:
        if ext == 'parquet':
            df.to_parquet(target_path, index=False)
        elif ext == 'csv':
            df.to_csv(target_path, index=False)
        else:
            print(f"WARNING: Unsupported file extension '{ext}' for file '{filename}'")
            return False
            
        print(f"SUCCESS: Saved to {target_path}")
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to save '{filename}': {str(e)}")
        return False


def download_from_s3(uri_dict, bucket_name=BUCKET_NAME):
    """
    Download files from S3 based on a dictionary of URIs.
    
    Args:
        uri_dict (dict): Dictionary with format {technique: [uris]}
                        where URIs are in format: FOLDER/{TECHNIQUE}/{LAYER}/{CLIENT}/{FILENAME.EXTENSION}
        bucket_name (str): Name of the S3 bucket
        
    Example:
        uri_dict = {
            'telemetry': ['MultiTechnique/telemetry/golden/cda/sample.parquet'],
            'oil': ['MultiTechnique/oil/silver/emin/data.csv']
        }
    """
    total_files = sum(len(uris) for uris in uri_dict.values())
    processed_files = 0
    successful_downloads = 0
    
    print(f"\n{'='*60}")
    print(f"Starting download of {total_files} files from S3")
    print(f"{'='*60}\n")
    
    for technique, uris in uri_dict.items():
        print(f"\n--- Processing technique: {technique} ---")
        print(f"Number of files: {len(uris)}\n")
        
        for uri in uris:
            processed_files += 1
            print(f"[{processed_files}/{total_files}] Processing: {uri}")
            
            # Parse the URI
            tech, layer, client, filename = parse_uri(uri)
            
            if not all([tech, layer, client, filename]):
                print(f"SKIP: Invalid URI format\n")
                continue
            
            # Verify technique matches the dictionary key
            if tech != technique:
                print(f"WARNING: Technique mismatch - URI has '{tech}' but expected '{technique}'")
            
            # Download from S3
            df = read_from_s3(uri, bucket_name)
            
            if df is not None:
                # Save locally
                if save_dataframe_locally(df, technique, layer, client, filename):
                    successful_downloads += 1
            
            print()  # Empty line for readability
    
    print(f"\n{'='*60}")
    print(f"Download Summary:")
    print(f"  Total files processed: {processed_files}")
    print(f"  Successfully downloaded: {successful_downloads}")
    print(f"  Failed: {processed_files - successful_downloads}")
    print(f"{'='*60}\n")


def main():
    """
    Main function to run the importer script.
    
    Update the uri_dict variable with your desired URIs to download.
    """
    # Example usage - Update this with your actual URIs
    uri_dict = {
        'telemetry': [
            'MultiTechnique/telemetry/golden/cda/sample.parquet',
            # Add more telemetry URIs here
        ],
        'oil': [
            'MultiTechnique/oil/golden/cda/oil_data.parquet',
            # Add more oil URIs here
        ]
    }
    
    # Run the download
    download_from_s3(uri_dict, bucket_name=BUCKET_NAME)


if __name__ == '__main__':
    main()
