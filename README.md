# Ocean Foundry

**Ocean Foundry** is a native Windows desktop tool for building Minecraft Java
**Ocean** and **Lava** surfaces - concrete foundations, coloured solid blocks and
stained glass - with a live colour preview and direct Litematica export.

## Download

Get the latest version from
[**Releases**](https://github.com/SirChomuske/ocean-foundry/releases/latest).

| Edition | File |
|---|---|
| English | `Ocean-Foundry-1.3.1.zip` |
| 中文 | `Ocean-Foundry-1.3.1-cn.zip` |

Download the ZIP, extract the **whole** folder, and run `Ocean Foundry.exe`.
Settings, imported normal maps and exports stay in that folder. Both portable
editions contain the same features.

## Features

- **Three generated wave sources** - FFT ocean spectrum, layered procedural
  waves and a Lua-style multi-band wave model - plus 13 bundled ocean normal
  maps and imported tangent-space normal maps.
- **Ocean and Lava materials** with concrete foundation shaping, shallow-water
  depth response, foam/whitecaps, reflections and view-dependent lighting.
- **Block-accurate baking** - solid colour matching, ordered stained-glass
  stacks, foam glass, palette dithering and Minecraft Java 26.1.2 block data.
- **Live Colour preview** before baking, plus component maps for colour, normals,
  foam, depth and reflection.
- **Portable exports and profiles** - Litematica structure exports and reusable
  project profiles.
- **English and Chinese** UI and user guides.

## Quick start

1. Choose **Ocean** or **Lava** in the material bar.
2. Pick a normal source: generated (FFT / Procedural / Lua), a bundled map, or
   your own normal map.
3. Shape the foundation, adjust wave size, spacing, wind and colour.
4. Use **Colour preview** to check the target, then **Bake**.
5. Export a Litematica structure or a block palette.

See the [User Guide](https://github.com/SirChomuske/ocean-foundry/blob/source/USER_GUIDE.md)
or [中文用户指南](https://github.com/SirChomuske/ocean-foundry/blob/source/USER_GUIDE.zh-CN.md)
for every control, and the
[Release Notes](https://github.com/SirChomuske/ocean-foundry/releases/latest)
for version changes.

## Source code

The application source is maintained on the
[**source branch**](https://github.com/SirChomuske/ocean-foundry/tree/source).
It is released under the MIT License.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 SirChocoo.

Bundled normal-map assets in the application are original works by the author
and are included under the same MIT license. Third-party libraries (NumPy,
SciPy, Pillow, PySide6/Qt, PyInstaller) retain their own licenses; the release
packages include their notices in `licenses/`.

## Notice

Minecraft is a trademark of Mojang and Microsoft. Ocean Foundry is an
independent project and is not an official Minecraft product, nor affiliated
with or endorsed by Mojang or Microsoft.

Created by SirChocoo.
