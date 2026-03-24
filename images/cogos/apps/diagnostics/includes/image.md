@{mnt/boot/cogos/includes/code_mode.md}

# Diagnostic: includes/image

Exercise the image API instructions above in read-only mode. Do NOT generate any images.

## Tasks

1. **Discover image capabilities**: Use `search("image")` to find available image operations. Print the result.

2. **List operations**: Using `run_code()`, print a list of all image operations you know about from the instructions: generate, resize, crop, rotate, convert, thumbnail, overlay_text, watermark, combine, describe, analyze, extract_text, edit, variations.

3. **Print summary**: Print `"image_diagnostic: operations_listed=true, generation_skipped=true"`.

```python verify
# Read-only diagnostic — just confirm the process completed
p = procs.get(name="_diag/inc_image")
if hasattr(p, "error"):
    pass
```
