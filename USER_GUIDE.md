# Ocean Foundry

## Start
1. Set the area and concrete waves.
2. Open **Colour & glass**, choose Ocean or Lava, then choose a normal source.
3. Set colours and press **Bake surface colours + glass**.
4. Drag to orbit, scroll to zoom, double-click to reset. N marks Minecraft north (−Z).
5. Export the complete build or separate layers.

**Colour preview** updates automatically, even before the first bake. Colours, reflections, foam, lighting, depth and normal-source controls update a small target image. Colour/light edits reuse cached fields; surface/foam changes recalculate only the sampled preview. Its right image shows the last fully baked blocks. Blending and material choices are shown after Bake. Export is disabled while settings are unbaked. Cancel retains the previous result.

New setups start with **Ocean normal library → Broken crests**, formerly named NormalMap. Saved profiles keep their selected source.

## Foundation
| Setting | Effect |
|---|---|
| Width / Length | Build area along X / Z, up to 1024 × 1024. |
| Placement Y | Export origin height. |
| Crest-to-trough height | Height of the large concrete waves. |
| Peak spacing | Distance between foundation waves. |
| Direction | 0° = +X, 90° = +Z. Surface waves follow this direction. |
| Irregularity | Variation between large waves. |
| Secondary swell detail | Smaller changes in concrete shape. |
| Crest choppiness | Sharpness of concrete peaks. |
| Seed / Random | Repeat a shape or choose a new arrangement. |
| Thickness | Shell thickness. Increase for steep waves. |

**Surface shell** is hollow underneath. **Solid to base** fills below the surface. **Use gentle foundation swells** applies a gentle geometry preset.

## Normal source and pattern
Only settings relevant to the selected mode are shown. Pattern settings are remembered per generator; Ocean colours and depth are shared between Ocean generators.

| Setting | Effect |
|---|---|
| Normal source | FFT spectrum, procedural wave groups, Lua wave model, Ocean library, Lava library or imported RGB normals. Each source shows only the controls it uses; colour, lighting and bake controls stay shared. |
| Lua wave layers | Lua wave model: stacks 1–8 complete wave bands, each with its own wavelength, direction turn and phase, into one normal map. |
| Main wave size | Generated surface feature size in blocks. |
| Link wave size to peak spacing | Generated modes: derives the surface wave size from the foundation peak spacing instead of Main wave size. |
| Wave size / peak spacing | Size of generated waves as a fraction of the foundation peak spacing; used while linking is on. |
| Link wave direction to foundation | Generated modes: waves follow the foundation heading. Disable to set an independent Wave direction; Ocean maps and Lava always share the foundation heading. |
| Wave direction · degrees | Heading of generated waves while direction linking is off. |
| Map span | Scale of source features; aspect ratio is preserved. |
| Shared direction offset (Ocean maps) | Rotates foundation, map waves and foam together. |
| Map rotation (Lava) | Rotates the map relative to foundation direction. |
| Normal strength | Strength of surface slopes used for lighting. |
| Pattern seed / Random | Changes pattern arrangement. |
| Invert normal map / light–dark | Reverses Ocean lighting; exchanges hot/cold Lava regions. |
| Reverse detected normal Y convention | Overrides automatic Ocean map Y conversion. |
| Flip map green channel (Lava) | Reverses the source map's Y convention. |

Ocean library/imported maps retain one common direction across translated patches, with narrow blended joins. Small sources can still repeat recognisable features. Import copies the image into the app's local assets. Static maps do not identify travel sign; a 180° shared offset reverses it.

## Ocean waves and depth
| Setting | Effect |
|---|---|
| Wind / roughness | Generated modes: more short-wave energy, crest sharpness and whitecaps. |
| Wind / foam activity | Image maps: changes foam activity while preserving source shape. |
| Crest choppiness (FFT) | Sharpens generated surface crests. |
| Peak concentration (FFT) | Concentrates energy near the main wavelength. |
| Directional spread | Variation in wave directions. |
| Small ripple strength | Amount of fine detail. |
| Small ripple / wave size (FFT) | Fine-wave size relative to main waves; requires nonzero ripple strength. |
| Swell strength / wavelength / direction offset | Amount, size and direction of an independent long-wave component. |
| Foundation slope influence | Generated modes only: adds smoothed concrete slopes to normals. |
| Shallowest depth | Minimum virtual depth. Does not move the concrete. |
| Depth slope | Depth increase per horizontal block. Zero gives uniform depth. |
| Depth rise across selection | Alternative to slope: sets total increase across the area. |
| Deeper direction | Direction in which the depth plane increases. |
| Depth refraction | Experimental generated-wave bending; zero disables it. |

Physical depth affects generated waves and breaking. It is separate from the depth controls in **Ocean colours**.

## Ocean colours
| Setting | Effect |
|---|---|
| Water colour | Underlying water hue before lit tint, reflections and foam. |
| Lit water colour | Tint applied through surface illumination. |
| Lit colour strength | 0 removes lit tint. 1 permits fully lit faces to use the lit colour entirely. |
| Depth colour influence | 0 removes depth from colour mixing only. 1 doubles lit tint at zero depth, capped at 100%. |
| Depth colour reach | Actual depth where the additional shallow-water tint reaches zero. |
| Wave shading strength | 0 applies lit tint evenly. 1 follows the full wave-face illumination. |
| Shadow softness | Softening radius in blocks for water-body shading only. |

The displayed tint percentages describe maximum contributions on fully illuminated faces. Water colour is not forced to dominate. Zero lit strength disables the related controls. Reflection and foam overlay this mixture. Colour changes do not alter normal shape or glass thickness.

## Reflection and foam
| Setting | Effect |
|---|---|
| Reflection colour / strength | Highlight tint and how strongly it covers the water. |
| Reflection softness | Broadens reflected highlights. |
| Light direction / elevation | Direction of illumination used during Bake. |
| Reflection view direction / elevation | Virtual viewing direction used to calculate fixed reflection highlights. |
| Foam colour | Colour of breaking foam. |
| Foam amount | Increases coverage of eligible crests; wind and depth still determine breaking activity. |
| Foundation crest foam bias | Small preference for foam near large concrete crests. |

Foam and reflections remain sharp when body shadows are softened. Baked lighting stays fixed while orbiting.

**Reflection view direction** is a compass bearing: 0° east (+X), 90° south (+Z),
180° west and 270° north. **Reflection view elevation** is the angle above the water:
low angles look across it; 90° looks straight down. These controls affect highlights,
not wave shape or placement. Orbiting the 3D preview does not change them.

Reflection strength controls the intensity of eligible highlights. Their coverage
depends on the surface normals, light and reflection view; even strength 1 can affect
very few pixels when these do not align. Softness broadens the highlight. Use the
live Colour preview to compare strength 0 versus 1 while adjusting the reflection view.

## Lava
| Setting | Effect |
|---|---|
| Cooled crust / Molten lava / Hottest lava | Colours of the three heat regions. |
| Crust coverage | Higher values show more cooled crust. |
| Baked glow strength | Brightness of hot regions; does not create a Minecraft light source. |
| Heat pattern | Slope or valley/fissure interpretation of the source normals. |
| Flow distortion | Bends the sampled pattern. |
| Lava extension | Classic overlapping patches; A/B remain experimental alternatives. |

## Materials, preview and export
| Setting | Effect |
|---|---|
| Include colour and glass | Off exports the concrete foundation only. |
| Use creative blocks | Allows creative-only materials, netherite blocks and ancient debris. Otherwise compatible survival materials are used. |
| Maximum solid block types | Limits the solid palette. |
| Prefer smooth block textures | Favours less patterned block textures. |
| Blending method / strength | Mixes nearby material colours; zero keeps hard boundaries. |
| Blending pattern size / seed | Size and arrangement of ordered/noise mixing. |
| Material replacements / exclusions | Substitute similar colours or prevent a block being selected. |
| Stained glass layers | Glass layers stacked above the solid coating, 0–3. Zero exports the solid blocks without glass. |
| Hardware acceleration | Uses supported GPU operations; CPU fallback remains available. |

Glass uses stained colours only. Coverage and restrained relief follow the surface; tint matching cannot change thickness. Strong foam replaces the top glass with white stained glass and medium foam with light-grey glass, so foam hugs the colour layer. Very faint foam adds one thin white layer above the tint stack (the Y-limit check reserves it), exportable as the Foam glass layer. Falling solid materials receive supports.

**Colour preview** compares the target with the Minecraft approximation and reports colour-match error. Small changes may select the same blocks. The material panel lists used solids and glass. **2D maps** separates depth, normals, target, solids, reflections and foam. **3D layer inspection / Cutaway** shows the structure; glass is opaque in layer inspection. Large previews simplify geometry; exports retain exact blocks.

Litematica omits air using separate occupied regions: keep all regions together. Turn off **Omit air in Litematica** for a smaller single-region file, then use ignore-air placement. WorldEdit uses `//paste -a`. Axiom skips empty space. All layers share X/Z origin 0 and the selected placement Y. Minecraft shaders and resource packs can differ from the preview.

Settings save automatically. **Save/Open profile** includes imported maps. History restores the last five baked settings; bake after restoring. Existing profiles retain their colours and sources and receive initial values for new controls. Extract portable releases before running; no separate Python installation is required.

### v1.3 wave, foam and swell controls
Hover over a slider's name for an explanation. Help appears beside the control
panel, accepts no mouse input, and disappears when the pointer leaves the name.
It stays clear of visible sliders and number boxes.

The **Lua wave model** stacks several complete Lua wave bands into one normal
map and then uses the same normal-map shading path as imported/library normals:
Normal strength, colours, lighting, reflections and foam behave like any other
normal source. Wind, swell and foundation-slope controls are hidden because this
source does not consume them. Increase **Lua wave layers** for finer stacked
crest structure; each layer adds a band with its own wavelength and direction.

FFT normals use a JONSWAP spectrum with frequency-dependent directional spreading
and smooth wave-band transitions. Procedural normals use overlapping wave trains
with longer crest groups. Directional spread controls their coherence; Small ripple
strength adds fine structure. These generate static surfaces, not animated fluid
or coastline simulations. Existing saved seeds remain deterministic in this build,
but generated patterns differ from earlier builds. Ocean library/imported normals
retain their source shapes. Body lighting now blends continuously on facing slopes;
Lit water strength and Wave shading strength still control the mixture.

FFT/procedural **Foam treatment** defaults to **Lua-style crests**: broken bright
crest details and scattered edges, always inside the existing foam regions.
**Lua whitecaps** uses crest compression, the downwind front slope and normalized
crest height; the Lua wave source always uses it. Choose **Legacy foam** for the
previous appearance. Library/imported Ocean maps use a normal-slope compression
proxy for whitecaps. Changing treatment updates the live target; Bake
applies it to blocks. It changes no wave normals or foundation.

**Swell** adds an independent long-period wave as normal detail only; it never
overwrites the colour layer or adds glass. **Wave spacing** (0.5-2.0) changes the
spacing of the foundation and shading waves together without changing wave height
or normal strength; 1.0 keeps the current layout.

Colour response preserves dark/lit contrast with a gentle continuous shoulder.
Smooth-texture preference is evaluated where each material is used, allowing
more useful shades up to Maximum solid block types. Uniform targets can still
use fewer types; materials are not added merely to fill the limit.

**Wave shading contrast** widens the dark-to-light range; **Wave shading midpoint**
balances how much of the surface is dark or lit. Their initial values (1 and 0.5)
preserve existing appearance. For a broad range, use Wave shading strength 1, allow
sufficient Lit colour strength, increase contrast and adjust midpoint until both
water colours appear. A lower midpoint favours light tones; a higher one favours
dark tones. These affect colour only and update the live preview immediately.
Blending strength and Maximum solid block types apply to the full Bake.

In the Lua-style treatment, scattered bright patches represent breaking whitewater;
finer residual foam is derived nearby behind those patches, inside the existing
eligible regions. This is a static visual approximation, not a timed fluid solver.
