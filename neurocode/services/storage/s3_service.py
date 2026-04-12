import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional
from dotenv import load_dotenv

                            
load_dotenv()


class S3Service:
    
    
    def __init__(self):
        
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        
        if not all([self.aws_access_key_id, self.aws_secret_access_key, self.bucket_name]):
            raise ValueError(
                "Missing required AWS credentials. Please set AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, and S3_BUCKET_NAME in environment variables."
            )
        
                              
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region
        )
    
    def generate_s3_key(
        self,
        organization_id: str,
        repository_id: str,
        branch: str,
        scope: str,
        documentation_id: Optional[str] = None,
        file_extension: str = "json"
    ) -> str:
        
        if documentation_id is None:
            from datetime import datetime
            documentation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
                                                 
        branch_safe = branch.replace("/", "_")
        
                      
        s3_key = (
            f"organizations/{organization_id}/"
            f"repositories/{repository_id}/"
            f"documentation/{branch_safe}/{scope}/"
            f"{documentation_id}.{file_extension}"
        )
        
        return s3_key

    def generate_onboarding_path_key(
        self,
        organization_id: str,
        path_id: str,
        file_extension: str = "json"
    ) -> str:
        
        return f"organizations/{organization_id}/onboarding/paths/{path_id}.{file_extension}"

    def upload_documentation(
        self,
        content: str,
        s3_key: str,
        content_type: str = "application/json"
    ) -> dict:
        
        try:
                          
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=content.encode('utf-8'),
                ContentType=content_type
            )
            
                             
            s3_url = f"s3://{self.bucket_name}/{s3_key}"
            
            return {
                "success": True,
                "s3_key": s3_key,
                "s3_url": s3_url,
                "bucket": self.bucket_name,
                "content_size": len(content.encode('utf-8'))
            }
            
        except NoCredentialsError:
            return {
                "success": False,
                "error": "AWS credentials not found or invalid"
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to upload to S3: {str(e)}"
            }
    
    def get_documentation(self, s3_key: str) -> dict:
        
        try:
                                
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
                          
            content = response['Body'].read().decode('utf-8')
            
            return {
                "success": True,
                "content": content,
                "content_type": response.get('ContentType', 'application/json'),
                "content_size": response.get('ContentLength', 0),
                "last_modified": response.get('LastModified')
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                return {
                    "success": False,
                    "error": f"Documentation not found: {s3_key}"
                }
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to retrieve from S3: {str(e)}"
            }
    
    def delete_documentation(self, s3_key: str) -> dict:
        
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            return {
                "success": True,
                "message": f"Documentation deleted: {s3_key}"
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to delete from S3: {str(e)}"
            }
    
    def check_connection(self) -> dict:
        
        try:
                                                                
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            
            return {
                "success": True,
                "message": f"Successfully connected to S3 bucket: {self.bucket_name}",
                "bucket": self.bucket_name,
                "region": self.aws_region
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404':
                return {
                    "success": False,
                    "error": f"Bucket not found: {self.bucket_name}"
                }
            elif error_code == '403':
                return {
                    "success": False,
                    "error": f"Access denied to bucket: {self.bucket_name}"
                }
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except NoCredentialsError:
            return {
                "success": False,
                "error": "AWS credentials not found or invalid"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to connect to S3: {str(e)}"
            }

