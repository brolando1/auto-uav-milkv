import json
import zipfile
import urllib.request
import shutil
from pathlib import Path

def ensure_dataset_is_present():
    """
    Checks if dataset/classification_test/training and validation exist.
    If not, downloads the zip from Zenodo and extracts it.
    """

    cfg_path = Path(__file__).parent / "config.json"
    if not cfg_path.exists():
        print(f"[ERROR] config.json not found at {cfg_path}")
        return
    
    with open(cfg_path, 'r') as f:
        cfg = json.load(f)

    val = (Path(__file__).parent / cfg.get("classification_root")).resolve()
    base = val.parent
    train = base / "training"
    url = cfg.get("dataset_download_url")

    if train.exists() and val.exists():
        if any(train.iterdir()) and any(val.iterdir()):
            print("[CHECK] Dataset already present and non-empty. Skipping download.")
            return 

    if not url:
        print("[BOOTSTRAP] Folders missing, but no 'dataset_download_url' in config. Skipping download.")
        return

    print(f"[BOOTSTRAP] Dataset missing. Downloading to {base}...")
    base.mkdir(parents=True, exist_ok=True)
    zip_tmp = base / "download_tmp.zip"
    extract_tmp = base / "temp_extract"
    internal_target_dir = extract_tmp / "dataset" / "classification_test"

    try:
        urllib.request.urlretrieve(url, zip_tmp)
        print("[BOOTSTRAP] Extracting files...")
        with zipfile.ZipFile(zip_tmp, 'r') as zip_ref:
            zip_ref.extractall(extract_tmp)

        internal_train = extract_tmp / "dataset" / "classification_test" / "training"
        internal_val = extract_tmp / "dataset" / "classification_test" / "validation"

        if not internal_train.exists() or not internal_val.exists():
            print(f"[ERROR] Could not find classification folders at {internal_target_dir}")
            print("Zip contents might have changed.")
            return

        if internal_train.exists():
            if train.exists(): 
                shutil.rmtree(train) 
            shutil.move(str(internal_train), str(train))

        if internal_val.exists():
            if val.exists(): 
                shutil.rmtree(val) 
            shutil.move(str(internal_val), str(val))
            
        print(f"[BOOTSTRAP] Dataset successfully initialized in {base}")
        
    except Exception as e:
        print(f"[ERROR] Automated dataset download failed: {e}")
    finally:
        if zip_tmp.exists():
            zip_tmp.unlink()
        if extract_tmp.exists(): 
            shutil.rmtree(extract_tmp)

if __name__ == "__main__":
    ensure_dataset_is_present()