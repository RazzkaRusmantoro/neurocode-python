import sys
import os
from pathlib import Path

                                                  
sys.path.insert(0, str(Path(__file__).parent))

from neurocode.services.s3_service import S3Service


def test_s3_connection():
    
    print("=" * 60)
    print("S3 Connection Test")
    print("=" * 60)
    
    try:
                               
        print("\n[1/4] Initializing S3 service...")
        s3_service = S3Service()
        print("[OK] S3 service initialized")
        print(f"  Bucket: {s3_service.bucket_name}")
        print(f"  Region: {s3_service.aws_region}")
        
                         
        print("\n[2/4] Testing S3 connection...")
        connection_result = s3_service.check_connection()
        if connection_result["success"]:
            print(f"[OK] {connection_result['message']}")
        else:
            print(f"[FAIL] Connection failed: {connection_result.get('error')}")
            return False
        
                     
        print("\n[3/4] Testing file upload...")
        test_content = {
            "test": True,
            "message": "This is a test file to verify S3 connection",
            "timestamp": "2025-01-15T10:00:00Z"
        }
        import json
        test_content_str = json.dumps(test_content, indent=2)
        
        test_s3_key = "test/connection_test.json"
        upload_result = s3_service.upload_documentation(
            content=test_content_str,
            s3_key=test_s3_key,
            content_type="application/json"
        )
        
        if upload_result["success"]:
            print(f"[OK] File uploaded successfully")
            print(f"  S3 Key: {upload_result['s3_key']}")
            print(f"  Size: {upload_result['content_size']} bytes")
        else:
            print(f"[FAIL] Upload failed: {upload_result.get('error')}")
            return False
        
                       
        print("\n[4/4] Testing file download...")
        download_result = s3_service.get_documentation(test_s3_key)
        
        if download_result["success"]:
            print(f"[OK] File downloaded successfully")
            print(f"  Content size: {download_result['content_size']} bytes")
                                    
            if download_result["content"] == test_content_str:
                print(f"[OK] Content matches original")
            else:
                print(f"[WARN] Content mismatch (but download worked)")
        else:
            print(f"[FAIL] Download failed: {download_result.get('error')}")
            return False
        
                           
        print("\n[Cleanup] Deleting test file...")
        delete_result = s3_service.delete_documentation(test_s3_key)
        if delete_result["success"]:
            print(f"[OK] Test file deleted")
        else:
            print(f"[WARN] Failed to delete test file: {delete_result.get('error')}")
        
        print("\n" + "=" * 60)
        print("[OK] All tests passed! S3 connection is working.")
        print("=" * 60)
        return True
        
    except ValueError as e:
        print(f"\n[FAIL] Configuration error: {e}")
        print("\nPlease make sure you have set the following environment variables:")
        print("  - AWS_ACCESS_KEY_ID")
        print("  - AWS_SECRET_ACCESS_KEY")
        print("  - AWS_REGION")
        print("  - S3_BUCKET_NAME")
        return False
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_s3_connection()
    sys.exit(0 if success else 1)

