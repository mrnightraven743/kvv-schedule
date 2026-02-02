import urequests
import gc
import os

# Link to your repository (Replace with your raw URL)
GITHUB_RAW_URL = "https://raw.githubusercontent.com/mrnightraven743/kvv-schedule/main/offline_data.py"

def update_from_github():
    print("--- GITHUB UPDATE START ---")
    gc.collect()
    try:
        print(f"Downloading...")
        res = urequests.get(GITHUB_RAW_URL)
        
        if res.status_code == 200:
            print("Download OK. Saving...")
            
            # Save to temporary file
            with open("offline_data.tmp", "w") as f:
                while True:
                    chunk = res.raw.read(256)
                    if not chunk: break
                    f.write(chunk)
            
            res.close()
            
            # Size check (>100 bytes means not empty)
            try:
                if os.stat("offline_data.tmp")[6] > 100:
                    try: os.remove("offline_data.py")
                    except: pass
                    os.rename("offline_data.tmp", "offline_data.py")
                    print("--- SUCCESS! File updated ---")
                    return True
                else:
                    print("Error: File too small")
                    return False
            except:
                print("Error checking file")
                return False
                
        else:
            print(f"HTTP Error: {res.status_code}")
            res.close()
            return False
            
    except Exception as e:
        print(f"Update Failed: {e}")
        return False