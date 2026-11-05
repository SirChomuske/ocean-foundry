# Ocean Foundry v1.3.1

4 November 2026 · Windows x64 · Created by SirChocoo

Ocean Foundry builds Minecraft Ocean and Lava surfaces from concrete foundations,
coloured solid blocks and stained glass. The English and Chinese portable editions
have the same features. Extract the complete archive before opening Ocean Foundry.exe.

## Changes since v1.3

- **Lua whitecaps follow the crest.** Foam is now judged inside each Lua wave band
  and carried by the owning band, producing a thin broken crest line instead of
  broad white patches.
- **Lua shading unchanged.** Lua still uses the existing Ocean Foundry normal-map
  colour and lighting path; only its foam changed.
- **Wave spacing.** A new 0.5-2.0 control changes the spacing of foundation and
  shading waves without changing wave height or normal strength.
- **UI stability.** Dragging a slider no longer rebuilds control visibility and
  no longer makes menus or combo boxes flicker.
- **Swell stays shading-only.** The swell-glass layer was removed; swell adds
  long-wave normal detail and never overwrites the colour layer.

## v1.3 changes since v1.2

- **Lua wave model.** A third generated normal source synthesizes the supplied
  Lua structure: six wave components, staggered wave groups, horizontal
  displacement and analytic slopes. Its elevation and foam inputs come from the
  same field, then feed the existing colour and lighting pipeline.
- **Lua whitecaps.** A new foam treatment judges whitecaps from horizontal
  compression, the downwind front slope and normalized crest height, with
  noise-fragmented residual foam. Available for FFT, procedural and Lua wave
  sources; library and imported normal maps use a calibrated normal-slope proxy.
- **Foam glass hugs the colour layer.** Strong foam replaces the top tint glass
  with white stained glass and medium foam with light-grey glass. Very faint foam
  adds one thin white layer above the tint stack. Exported as the new Foam glass
  layer; the Y-limit check reserves it.
- **Swell glass.** The independent long swell adds a thin bleached layer on its
  upper crest fraction. Colour follows the local ocean colour, lightened toward
  white and matched to stained glass. Crest fraction and bleaching strength are
  adjustable; foam layers sit above swell glass and both share the Foam glass
  export layer.
- **Maintenance fixes since the 1.2 package.** One source for defaults, unified
  error diffusion, consistent refraction scaling, selectable 0-3 glass layers,
  wave-size/direction linking controls, a 1130 px minimum window width, and a
  native-platform test suite.
- **Onedir development build.** The development executable ships as
  Ocean Foundry.exe plus _internal, matching the portable release layout.

## Upgrade

Close the old app normally and back up its folder. Extract v1.3 into the same
folder and replace application files. Keep settings.json, settings.bak,
normal_maps, profiles and exports. Existing colours and source selections are
retained; new controls receive initial values. Older bakes may differ when
regenerated with the updated model.

## Known limits

- RGB/alpha glass compositing approximates Minecraft. Connected glass, resource
  packs, shaders and viewing angle can change the result. No new in-game
  Complementary shader or minimap validation was performed for this release.
- Map-source whitecaps use a slope-compression proxy; a static normal map cannot
  determine physical travel sign. Coverage is bounded, not a physical breaking
  model.
- Foam and swell share the Foam glass export layer, and swell glass adds at most
  one layer above the tint stack; foam sits above it.
- Small source images can still repeat motifs. A limited block palette can map
  small colour changes to identical blocks.
- Large bakes and diffusion blending can take time and memory. Air-free
  Litematica can contain many regions; keep them together.

Terrain collision and normal-map-derived foundations are not part of v1.3.
