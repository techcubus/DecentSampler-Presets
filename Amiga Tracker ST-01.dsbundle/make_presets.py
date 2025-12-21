#!/usr/bin/env python3
import struct
import sys
from pathlib import Path


def read_u32le(f):
    """Read an unsigned 32-bit little-endian integer."""
    data = f.read(4)
    if len(data) != 4:
        raise EOFError("Unexpected end of file while reading u32")
    return struct.unpack("<I", data)[0]


def find_chunk(f, fourcc: bytes):
    """
    Find a RIFF chunk by its 4-byte ID (fourcc).
    Returns (data_pos, size) or (None, None) if not found.
    """
    # Skip RIFF header: "RIFF" + size + "WAVE" = 12 bytes
    f.seek(0)
    header = f.read(12)
    if len(header) != 12 or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("Not a valid RIFF/WAVE file")

    while True:
        hdr = f.read(8)
        if len(hdr) < 8:
            # No more chunks
            return None, None

        chunk_id, size = struct.unpack("<4sI", hdr)

        if chunk_id == fourcc:
            # We are positioned right after the header, at the start of the data
            return f.tell(), size

        # Skip this chunk's data (+ padding if odd size)
        skip = size + (size & 1)
        f.seek(skip, 1)


def read_fmt_metadata(f):
    """
    Read basic info from the 'fmt ' chunk: channels, sample rate, bits per sample.
    Returns a dict or None if fmt chunk not found.
    """
    pos, size = find_chunk(f, b"fmt ")
    if pos is None:
        return None

    f.seek(pos)
    # Standard PCM "fmt " chunk is 16 bytes of data (for basic WAV)
    if size < 16:
        raise ValueError("fmt chunk too small")

    # More explicit parsing:
    f.seek(pos)
    fmt_data = f.read(16)
    (audio_format,
     num_channels,
     sample_rate,
     byte_rate,
     block_align,
     bits_per_sample) = struct.unpack("<HHIIHH", fmt_data)

    return {
        "audio_format": audio_format,
        "num_channels": num_channels,
        "sample_rate": sample_rate,
        "bits_per_sample": bits_per_sample,
    }


def read_smpl_metadata(f):
    """
    Read loop / root key info from the 'smpl' chunk.
    Returns:
    {
      "root_key": int or None,
      "loops": [
         {"start": int, "end": int, "type": int, "play_count": int},
         ...
      ]
    }
    or None if no smpl chunk.
    """
    pos, size = find_chunk(f, b"smpl")
    if pos is None:
        return None

    f.seek(pos)

    # smpl header is at least 9 * 4 bytes = 36 bytes (manufacturer..sampler_data)
    if size < 36:
        raise ValueError("smpl chunk too small")

    manufacturer   = read_u32le(f)
    product        = read_u32le(f)
    sample_period  = read_u32le(f)
    midi_unity     = read_u32le(f)  # root key
    pitch_fraction = read_u32le(f)
    smpte_format   = read_u32le(f)
    smpte_offset   = read_u32le(f)
    num_loops      = read_u32le(f)
    sampler_data   = read_u32le(f)

    loops = []
    for _ in range(num_loops):
        # Each loop struct is 6 * 4 bytes = 24 bytes
        cue_id     = read_u32le(f)
        loop_type  = read_u32le(f)
        start      = read_u32le(f)
        end        = read_u32le(f)
        fraction   = read_u32le(f)
        play_count = read_u32le(f)
        loops.append({
            "cue_id": cue_id,
            "type": loop_type,
            "start": start,
            "end": end,
            "fraction": fraction,
            "play_count": play_count,
        })

    return {
        "root_key": midi_unity,
        "loops": loops,
    }


def read_sample_length(f, fmt_meta):
    """
    Compute the number of samples (frames) from the 'data' chunk.
    Returns an integer count of samples, or None if something is missing.
    """
    if fmt_meta is None:
        return None

    # Find the 'data' chunk: this gives us the number of *bytes* of audio
    pos, size = find_chunk(f, b"data")
    if pos is None:
        return None

    num_channels = fmt_meta["num_channels"]
    bits_per_sample = fmt_meta["bits_per_sample"]

    # bytes per single sample frame (all channels)
    bytes_per_frame = num_channels * bits_per_sample // 8
    if bytes_per_frame == 0:
        return None

    # Number of frames = data_bytes / bytes_per_frame
    return size // bytes_per_frame


def load_template(template_path: Path) -> str:
    return template_path.read_text(encoding="utf-8")


def make_preset_text(template: str, wav_path: Path, fmt_meta, smpl_meta, sample_length) -> str:
    """
    Replace {{PLACEHOLDER}} tokens in the template with values
    derived from the WAV metadata.
    """
    # Basic values
    wav_filename = wav_path.name
    wav_basename = wav_path.stem

    sample_rate = fmt_meta["sample_rate"] if fmt_meta else 44100

    # --- new: sample-level info ---
    # If we couldn't compute length, fall back to 0
    if sample_length is None:
        sample_length = 0

    sample_start = 0                      # always start at first sample
    sample_end = max(sample_length - 1, 0)  # last valid sample index

    root_key = None
    loop_start = None
    loop_end = None
    has_loop = False

    if smpl_meta is not None:
        root_key = smpl_meta["root_key"]
        if smpl_meta["loops"]:
            loop = smpl_meta["loops"][0]  # take first loop
            loop_start = loop["start"]
            loop_end = loop["end"]
            has_loop = True

    # Fallbacks if missing
    if root_key is None:
        # Default to MIDI 60 (middle C) if not defined
        root_key = 60

    if loop_start is None:
        loop_start = 0
    if loop_end is None:
        loop_end = 0

    # --- replacement map: this is where we expose everything to the template ---
    replacements = {
        "{{WAV_FILENAME}}": wav_filename,
        "{{WAV_BASENAME}}": wav_basename,
        "{{ROOT_KEY}}": str(root_key),
        "{{LOOP_START}}": str(loop_start),
        "{{LOOP_END}}": str(loop_end),
        "{{HAS_LOOP}}": "true" if has_loop else "false",
        "{{SAMPLE_RATE}}": str(sample_rate),
        "{{SAMPLE_LENGTH_SAMPLES}}": str(sample_length),
        "{{SAMPLE_START}}": str(sample_start),
        "{{SAMPLE_END}}": str(sample_end),

    }

    result = template
    for key, value in replacements.items():
        result = result.replace(key, value)

    return result


def process_directory(wav_dir: Path, template_path: Path, out_dir: Path):
    template_text = load_template(template_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    for wav_path in sorted(wav_dir.glob("*.wav")):
        try:
            with wav_path.open("rb") as f:
                fmt_meta = read_fmt_metadata(f)
                smpl_meta = read_smpl_metadata(f)
                sample_length = read_sample_length(f, fmt_meta)

            preset_text = make_preset_text(
                template_text, 
                wav_path, 
                fmt_meta, 
                smpl_meta,
                sample_length,
                )

            preset_name = wav_path.stem + ".dspreset"
            out_path = out_dir / preset_name
            out_path.write_text(preset_text, encoding="utf-8")

            print(f"Created preset: {out_path}")
        except Exception as e:
            print(f"Error processing {wav_path}: {e}", file=sys.stderr)


def main(argv):
    if len(argv) != 4:
        print("Usage: make_presets.py <wav_dir> <template.dspreset> <output_dir>")
        sys.exit(1)

    wav_dir = Path(argv[1])
    template_path = Path(argv[2])
    out_dir = Path(argv[3])

    if not wav_dir.is_dir():
        print(f"Not a directory: {wav_dir}")
        sys.exit(1)
    if not template_path.is_file():
        print(f"Template file not found: {template_path}")
        sys.exit(1)

    process_directory(wav_dir, template_path, out_dir)


if __name__ == "__main__":
    main(sys.argv)
