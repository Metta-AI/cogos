## Image generation and manipulation

You can generate, manipulate, and analyze images using the `image` capability. All image operations use blob keys.

### Generate an image
```python
ref = image.generate("a cute dog playing in the park")
# ref.url  — presigned S3 URL (use in HTML <img src=...>)
# ref.key  — blob storage key (use with discord files=[ref.key])
```

### Embed in a website
```python
ref = image.generate("a sunset")
html = f'<img src="{ref.url}">'  # Use ref.url for HTML img tags
web.publish("page/index.html", html)
```

### Send as Discord attachment
```python
discord.send(channel=channel_id, content="Here's your image!", reply_to=message_id, files=[ref.key])
# Or DM it
discord.dm(user_id=author_id, content="Here's your image!", files=[ref.key])
```

### Other operations
- `image.resize(key, width?, height?)` — resize (auto-aspect if one dim omitted)
- `image.crop(key, left, top, right, bottom)` — crop region
- `image.rotate(key, degrees)` — rotate
- `image.convert(key, format)` — convert format (PNG, JPEG, WEBP)
- `image.thumbnail(key, max_size)` — fit within box
- `image.overlay_text(key, text, position?, font_size?, color?)` — add text
- `image.watermark(key, watermark_key, position?, opacity?)` — add watermark
- `image.combine(keys, layout?)` — stitch images (horizontal/vertical/grid)
- `image.describe(key, prompt?)` — describe/caption image
- `image.analyze(key, prompt)` — answer questions about image
- `image.extract_text(key)` — OCR
- `image.edit(key, prompt)` — edit image with prompt
- `image.variations(key, count?)` — generate variations
