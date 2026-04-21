"""
Build script for creating a standalone Windows executable.

Usage:
    python build_exe.py

Prerequisites:
    pip install pyinstaller

This script:
    1. Checks that PyInstaller is available
    2. Runs PyInstaller with the spec file
    3. Reports the output location and size

The resulting executable will be in dist/ueye-timelapse/
Zip that folder for distribution.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ICO_SIZES = [16, 32, 48, 64, 128, 256]
PNG_SOURCE = Path("ueyetimelapse_icon_SQUARE_CROPPED.png")
ICO_OUTPUT = Path("ueyetimelapse_icon.ico")


def create_icon():
    from PIL import Image
    if not PNG_SOURCE.exists():
        print(f"Warning: icon source not found ({PNG_SOURCE}), skipping ICO generation.")
        return
    img = Image.open(PNG_SOURCE).convert("RGBA")
    imgs = [img.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    imgs[0].save(ICO_OUTPUT, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                 append_images=imgs[1:])
    print(f"Icon created: {ICO_OUTPUT}")


def main():
    # Check platform
    if sys.platform != "win32":
        print(
            "WARNING: PyInstaller builds are platform-specific.\n"
            "You are not on Windows — the resulting executable will be\n"
            "for your current platform, not Windows.\n"
        )

    create_icon()

    # Check PyInstaller is available
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("PyInstaller is not installed.")
        print("Install it with: pip install pyinstaller")
        sys.exit(1)

    spec_file = Path("ueye_timelapse.spec")
    if not spec_file.exists():
        print(f"Error: spec file not found: {spec_file}")
        sys.exit(1)

    # Clean previous builds
    dist_dir = Path("dist") / "ueye-timelapse"
    if dist_dir.exists():
        print(f"Cleaning previous build: {dist_dir}")
        shutil.rmtree(dist_dir)

    build_dir = Path("build")
    if build_dir.exists():
        print(f"Cleaning build directory: {build_dir}")
        shutil.rmtree(build_dir)

    # Run PyInstaller
    print("\nBuilding executable...")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(spec_file), "--noconfirm"],
        cwd=str(Path.cwd()),
    )

    if result.returncode != 0:
        print("\nBuild FAILED.")
        sys.exit(1)

    print("=" * 60)

    # Report results
    if dist_dir.exists():
        exe_path = dist_dir / "ueye-timelapse.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\nBuild successful!")
            print(f"  Executable: {exe_path}")
            print(f"  Size: {size_mb:.1f} MB")
        else:
            print(f"\nBuild directory created but .exe not found.")
            print(f"  Check: {dist_dir}")

        # Calculate total folder size
        total = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file())
        total_mb = total / (1024 * 1024)
        print(f"  Total folder size: {total_mb:.1f} MB")
        print(f"\nTo distribute: zip the '{dist_dir}' folder and upload")
        print(f"to GitHub Releases.")
    else:
        print("\nBuild directory not found. Check PyInstaller output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()