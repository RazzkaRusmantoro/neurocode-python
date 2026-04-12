import os
import sys
from dotenv import load_dotenv

                            
load_dotenv()

                                                  
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from neurocode.services.mongodb_service import MongoDBService

def test_mongodb_connection():
    
    print("=" * 60)
    print("Testing MongoDB Connection")
    print("=" * 60)
    
    try:
                                    
        print("\n[1] Initializing MongoDB service...")
        mongodb_service = MongoDBService()
        print("    [OK] MongoDB service initialized")
        
                         
        print("\n[2] Testing connection...")
        result = mongodb_service.check_connection()
        
        if result.get("success"):
            print("    [OK] Connection successful!")
            print(f"    Database: {result.get('database')}")
            print(f"    Collections: {len(result.get('collections', []))}")
            print(f"    Collection names: {', '.join(result.get('collections', []))}")
            
            stats = result.get('stats', {})
            print(f"\n    Database Stats:")
            print(f"    - Collections: {stats.get('collections', 0)}")
            print(f"    - Data Size: {stats.get('dataSize', 0)} bytes")
            print(f"    - Storage Size: {stats.get('storageSize', 0)} bytes")
            
            print("\n" + "=" * 60)
            print("MongoDB connection test: SUCCESS")
            print("=" * 60)
            return True
        else:
            print(f"    [FAIL] Connection failed: {result.get('error')}")
            print("\n" + "=" * 60)
            print("MongoDB connection test: FAILED")
            print("=" * 60)
            return False
            
    except ValueError as e:
        print(f"    [FAIL] Configuration error: {e}")
        print("\n    Please set MONGODB_URI in your .env file")
        print("    Example: MONGODB_URI=mongodb://localhost:27017")
        print("\n" + "=" * 60)
        print("MongoDB connection test: FAILED")
        print("=" * 60)
        return False
    except Exception as e:
        print(f"    [FAIL] Unexpected error: {e}")
        print("\n" + "=" * 60)
        print("MongoDB connection test: FAILED")
        print("=" * 60)
        return False
    finally:
                          
        if 'mongodb_service' in locals():
            mongodb_service.close()

if __name__ == "__main__":
    success = test_mongodb_connection()
    sys.exit(0 if success else 1)

