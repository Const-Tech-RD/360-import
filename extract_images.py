import shutil
import zipfile
from pathlib import Path

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}


def extract_from_zip(src_path: Path, out_dir: Path, media_prefix: str) -> list[Path]:
    """Extract images from a ZIP-based Office doc (docx or xlsx)."""
    extracted = []
    try:
        with zipfile.ZipFile(src_path) as z:
            for name in z.namelist():
                if not name.startswith(media_prefix):
                    continue
                relative = name[len(media_prefix):]
                if not relative or '/' in relative:
                    continue  # skip subdirectories
                ext = Path(name).suffix.lower()
                if ext not in IMAGE_EXTS:
                    continue
                idx = len(extracted)
                out_name = f"{src_path.stem}_{idx}{ext}"
                out_path = out_dir / out_name
                out_path.write_bytes(z.read(name))
                extracted.append(out_path)
    except Exception as e:
        print(f"  Warning: could not read {src_path.name}: {e}")
    return extracted


MIN_IMAGE_BYTES = 500  # skip tiny blobs that are likely thumbnails or artifacts


def extract_from_xls(src_path: Path, out_dir: Path) -> list[Path]:
    """Extract images from a legacy .xls by scanning raw bytes for image magic.

    Uses a greedy first-match strategy: JPEG blobs are sliced at the first
    FF D9 byte pair found after the SOI marker, which may truncate files that
    contain embedded thumbnails or raw scan data with internal EOI-like bytes.
    PNG extraction is reliable because the IEND chunk is a fixed 12-byte
    sequence that does not appear in valid PNG content.
    """
    data = src_path.read_bytes()
    extracted = []
    idx = 0

    # ── JPEG: FF D8 FF … FF D9 ──────────────────────────────────────────────
    JPEG_START = b'\xff\xd8\xff'
    JPEG_END   = b'\xff\xd9'
    pos = 0
    while True:
        start = data.find(JPEG_START, pos)
        if start == -1:
            break
        end = data.find(JPEG_END, start + 3)
        if end == -1:
            break
        end += 2
        blob = data[start:end]
        if len(blob) >= MIN_IMAGE_BYTES:
            out_path = out_dir / f"{src_path.stem}_{idx}.jpg"
            out_path.write_bytes(blob)
            extracted.append(out_path)
            idx += 1
        pos = end

    # ── PNG: 89 50 4E 47 … 49 45 4E 44 AE 42 60 82 ─────────────────────────
    PNG_START = b'\x89PNG\r\n\x1a\n'
    PNG_END   = b'IEND\xaeB`\x82'
    pos = 0
    while True:
        start = data.find(PNG_START, pos)
        if start == -1:
            break
        end = data.find(PNG_END, start)
        if end == -1:
            break
        end += len(PNG_END)
        blob = data[start:end]
        if len(blob) >= MIN_IMAGE_BYTES:
            out_path = out_dir / f"{src_path.stem}_{idx}.png"
            out_path.write_bytes(blob)
            extracted.append(out_path)
            idx += 1
        pos = end

    return extracted


def copy_loose_image(src_path: Path, out_dir: Path) -> Path | None:
    """Copy a standalone image file into out_dir, avoiding name collisions."""
    dest = out_dir / src_path.name
    if dest.exists():
        dest = out_dir / f"{src_path.parent.name}_{src_path.name}"
    if dest.exists():
        # Still collides — append incrementing counter
        stem = src_path.stem
        ext  = src_path.suffix
        idx  = 1
        while dest.exists():
            dest = out_dir / f"{src_path.parent.name}_{stem}_{idx}{ext}"
            idx += 1
    shutil.copy2(src_path, dest)
    return dest


def main(media_dir: Path, out_dir: Path) -> int:
    """Walk media_dir, extract all images into out_dir. Returns total count."""
    out_dir.mkdir(exist_ok=True)
    total = 0

    for path in sorted(media_dir.rglob('*')):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        extracted = []

        if ext == '.docx':
            extracted = extract_from_zip(path, out_dir, 'word/media/')
        elif ext == '.xlsx':
            extracted = extract_from_zip(path, out_dir, 'xl/media/')
        elif ext == '.xls':
            extracted = extract_from_xls(path, out_dir)
        elif ext in IMAGE_EXTS:
            result = copy_loose_image(path, out_dir)
            if result:
                extracted = [result]

        if extracted:
            print(f"  {path.name}: {len(extracted)} image(s)")
            total += len(extracted)

    print(f"\nTotal: {total} image(s) extracted to {out_dir}/")
    return total


if __name__ == '__main__':
    import sys
    media = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('MEDIA-20260415T015452Z-3-001/MEDIA/fotos pagina web')
    out   = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('extracted_images')
    main(media, out)
