#!/usr/bin/env python3
"""Build the shared Godot UI theme and its editable, pixel-aligned SVG hardware.

No raster processing. Run from any directory; generated resources are checked in.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "client"
ART = ROOT / "assets/ui/grimdark"
ART.mkdir(parents=True, exist_ok=True)


def svg(name, width, height, body):
    # HUD overlays have a genuinely transparent trough. Clip outside it so fills
    # cannot be occluded by the metal plate's otherwise opaque interior.
    aperture = {"health_frame": (46, 13, 233, 19), "mana_frame": (46, 13, 233, 19), "stamina_frame": (10, 6, 298, 6)}.get(name)
    if aperture:
        x, y, w, h = aperture
        body = f'<defs><clipPath id="rim"><path clip-rule="evenodd" d="M0 0H{width}V{height}H0ZM{x} {y}V{y+h}H{x+w}V{y}Z"/></clipPath></defs><g clip-path="url(#rim)">{body}</g>'
    (ART / f"{name}.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges">{body}</svg>\n'
    )


def hardware(w, h, inside, edge="#776544"):
    s = f'<path d="M6 0H{w-6}V3H{w-3}V6H{w}V{h-6}H{w-3}V{h-3}H{w-6}V{h}H6V{h-3}H3V{h-6}H0V6H3V3H6Z" fill="#050706"/>'
    for inset, color in [(3, "#454640"), (4, "#151918"), (6, edge), (7, "#070a0b"), (9, inside)]:
        s += f'<rect x="{inset}" y="{inset}" width="{w-inset*2}" height="{h-inset*2}" fill="{color}"/>'
    s += f'<path d="M12 10H{w-12}M10 12V{h-12}" stroke="#ffffff" stroke-opacity=".07"/>'
    for x, y, sx, sy in [(4,4,1,1),(w-4,4,-1,1),(4,h-4,1,-1),(w-4,h-4,-1,-1)]:
        s += f'<g transform="translate({x} {y}) scale({sx} {sy})"><path d="M0 0H16L10 4H5V10L0 16Z" fill="#95815b"/><path d="M2 2H10L4 4V10L2 12Z" fill="#c1b18a"/><rect x="5" y="5" width="3" height="3" fill="#050706"/><rect x="5" y="5" width="2" height="2" fill="#b28b42"/></g>'
    return s


for name, fill, edge in [("button", "#161a1b", "#776544"), ("button_hover", "#282521", "#c0a066"), ("button_pressed", "#080b0d", "#ad7940"), ("button_disabled", "#101314", "#393d39"), ("button_primary", "#501818", "#ab7944"), ("button_primary_hover", "#782321", "#d4ae6e")]:
    svg(name, 160, 48, hardware(160, 48, fill, edge))
svg("panel", 128, 128, hardware(128, 128, "#0c1012", "#5f533d"))
svg("caret", 12, 8, '<path d="M0 0H3V2H5V4H7V2H9V0H12V3H10V5H8V7H4V5H2V3H0Z" fill="#c5ae7b"/>')
svg("grabber", 16, 22, '<path d="M8 0L15 7V15L8 22L1 15V7Z" fill="#060809"/><path d="M8 2L13 8V14L8 20L3 14V8Z" fill="#ac8c4e"/><path d="M8 4L11 9V13L8 17L5 13V9Z" fill="#e2d2a6"/>')
svg("check_off", 20, 20, '<rect x="1" y="1" width="18" height="18" fill="#090c0e" stroke="#766647"/><path d="M3 3H17M3 3V17" stroke="#353b3c"/>')
svg("check_on", 20, 20, '<rect x="1" y="1" width="18" height="18" fill="#261d13" stroke="#c1a168"/><path d="M5 9L8 13L15 5" fill="none" stroke="#e4ce96" stroke-width="2"/>')

for kind, colors in {"health": ["#5d0f16", "#a2232c", "#e15055", "#c1313d", "#8b1c2a"], "mana": ["#112849", "#215e9b", "#66a4d6", "#367cbb", "#1d497b"], "stamina": ["#65441b", "#bd842b", "#ecd389", "#d5a341", "#9c6924"]}.items():
    body = '<rect width="256" height="20" fill="'+colors[0]+'"/>'
    for y, h, c in [(1,2,colors[2]), (3,5,colors[1]), (8,5,colors[3]), (13,6,colors[4])]:
        body += f'<rect x="1" y="{y}" width="254" height="{h}" fill="{c}"/>'
    svg(f"{kind}_fill", 256, 20, body)
svg("track", 256, 20, '<rect width="256" height="20" fill="#080b0e"/><path d="M0 1H256" stroke="#3c2926"/><path d="M0 18H256" stroke="#252b2d"/>')

for kind in ["health", "mana"]:
    s = '<path d="M39 7H284L299 22L284 37H39L32 22Z" fill="#050706"/><path d="M41 9H283L296 22L283 35H41L35 22Z" fill="#414540"/><path d="M43 11H282L293 22L282 33H43Z" fill="#0a0d0e"/>'
    s += '<path d="M46 12H279M46 32H279M281 12L291 22L281 32" fill="none" stroke="#a28a53"/><path d="M49 10H276M49 34H276" stroke="#6d5a38"/>'
    s += '<path d="M22 0L28 5H35V11L42 22L35 33V39H28L22 44L16 39H9V33L2 22L9 11V5H16Z" fill="#080b0d" stroke="#696652"/><path d="M22 4L36 14V30L22 40L8 30V14Z" fill="#1b2020" stroke="#a28a53"/>'
    if kind == "health":
        s += '<path d="M16 11H27V13H30V25H27V32H17V27H13V15H16Z" fill="#aca58c"/><path d="M17 12H26V14H28V19H15V15H17Z" fill="#d8d0bc"/><path d="M16 20H20V24H16ZM24 20H28V24H24ZM21 25H24V28H21ZM19 30H20V33H19ZM24 30H25V33H24Z" fill="#101311"/>'
    else:
        s += '<path d="M22 9L30 22L22 35L14 22Z" fill="#173959" stroke="#b7ad86"/><path d="M22 13L26 22L22 29L18 22Z" fill="#5799c2"/><path d="M22 14V27L18 22Z" fill="#93c5d8"/>'
    for x in [47, 277]:
        s += f'<rect x="{x}" y="9" width="2" height="2" fill="#d5b975"/><rect x="{x}" y="33" width="2" height="2" fill="#9b7428"/>'
    svg(f"{kind}_frame", 300, 44, s)
svg("stamina_frame", 318, 18, '<path d="M5 2H313L318 9L313 16H5L0 9Z" fill="#070a0b" stroke="#58594c"/><path d="M8 4H310V14H8Z" fill="#88703b"/><path d="M9 5H309V13H9Z" fill="#080b0d"/><path d="M12 3H306M12 15H306" stroke="#c6aa6c"/>')
svg("slot", 48, 48, hardware(48, 48, "#111719"))
svg("minimap_frame", 200, 200, '<path fill-rule="evenodd" d="M0 0H200V200H0ZM12 12V188H188V12Z" fill="#0a0e10"/><path d="M2 2H198V198H2Z" fill="none" stroke="#53574e"/><path d="M6 6H194V194H6Z" fill="none" stroke="#967c47"/><path d="M10 10H190V190H10Z" fill="none" stroke="#333a39"/>' + ''.join(f'<path d="M{x} {y}h{d*19}v{d*4}h{-d*15}v{d*15}h{-d*4}Z" fill="#bd9d5f"/>' for x,y,d in [(1,1,1),(199,199,-1)]) + '<path d="M100 1L106 6L100 11L94 6Z M100 189L106 194L100 199L94 194Z" fill="#c5a05b"/>')

# Theme resource: one shared source for native controls, including generated buttons.
ext, sub, props = [], [], []


def texture(name):
    key = "tex_" + name
    entry = f'[ext_resource type="Texture2D" path="res://assets/ui/grimdark/{name}.svg" id="{key}"]'
    if entry not in ext:
        ext.append(entry)
    return f'ExtResource("{key}")'


def textured(name, margins=(16, 12, 16, 12), patch=16):
    sub.append(f'[sub_resource type="StyleBoxTexture" id="{name}"]\ntexture = {texture(name)}\n' + '\n'.join(f'texture_margin_{side} = {patch}.0\ncontent_margin_{side} = {val}.0' for side,val in zip(['left','top','right','bottom'],margins)))
    return f'SubResource("{name}")'


def flat(name, bg, border="Color(0, 0, 0, 0)", width=0, margins=(8, 6, 8, 6)):
    sub.append(f'[sub_resource type="StyleBoxFlat" id="{name}"]\nbg_color = {bg}\nborder_color = {border}\n' + '\n'.join(f'border_width_{s} = {width}\ncontent_margin_{s} = {v}.0' for s,v in zip(['left','top','right','bottom'],margins)))
    return f'SubResource("{name}")'


def prop(t, kind, name, value):
    props.append(f'{t}/{kind}/{name} = {value}')


bone = 'Color(0.85, 0.82, 0.74, 1)'
gold = 'Color(0.78, 0.65, 0.42, 1)'
muted = 'Color(0.57, 0.58, 0.55, 1)'
normal = textured("button")
hover = textured("button_hover")
pressed = textured("button_pressed")
disabled = textured("button_disabled")
primary = textured("button_primary")
primary_hover = textured("button_primary_hover")
panel = textured("panel", (24, 24, 24, 24), 24)
focus = flat("focus", 'Color(0,0,0,0)', 'Color(0.9,0.76,0.48,1)', 1, (0,0,0,0))
input_box = flat("input", 'Color(0.035,0.045,0.052,1)', 'Color(0.30,0.29,0.24,1)', 1, (12,10,12,10))
separator = flat("separator", 'Color(0.29,0.25,0.18,1)', margins=(0,1,0,1))
track = flat("slider", 'Color(0.025,0.035,0.04,1)', 'Color(0.25,0.27,0.26,1)', 1, (0,3,0,3))
fill = flat("slider_fill", 'Color(0.55,0.40,0.20,1)', margins=(0,3,0,3))
empty = flat("empty", 'Color(0,0,0,0)', margins=(8,6,8,6))
for t in ["Button", "OptionButton"]:
    for state, box in dict(normal=normal, hover=hover, pressed=pressed, disabled=disabled, focus=focus).items():
        prop(t,"styles",state,box)
    for state, col in dict(font_color=bone,font_hover_color='Color(1,0.93,0.78,1)',font_pressed_color=gold,font_disabled_color=muted,font_focus_color='Color(1,0.93,0.78,1)').items():
        prop(t,"colors",state,col)
    prop(t,"font_sizes","font_size",18)
props += ['PrimaryButton/base_type = &"Button"', 'DisplayLabel/base_type = &"Label"']
prop("PrimaryButton","styles","normal",primary)
prop("PrimaryButton","styles","hover",primary_hover)
ext.append('[ext_resource type="FontFile" path="res://assets/fonts/CormorantUnicase-Bold.ttf" id="display_font"]')
for t in ["Button","OptionButton","DisplayLabel","TabBar","TabContainer"]:
    prop(t,"fonts","font",'ExtResource("display_font")')
prop("DisplayLabel","colors","font_color",bone)
prop("DisplayLabel","font_sizes","font_size",32)
for t in ["Label","RichTextLabel","CheckButton","CheckBox","LineEdit","PopupMenu","TabBar"]:
    prop(t,"colors","font_color",bone)
prop("Label","colors","font_shadow_color",'Color(0,0,0,0.8)')
prop("Label","constants","shadow_offset_y",1)
prop("OptionButton","constants","arrow_margin",14)
prop("OptionButton","constants","h_separation",12)
prop("OptionButton","icons","arrow",texture("caret"))
# Right content margin reserves the value/arrow separation even with long labels.
for state, source in [("normal","button"),("hover","button_hover"),("pressed","button_pressed"),("disabled","button_disabled")]:
    name = "option_" + state
    sub.append(f'[sub_resource type="StyleBoxTexture" id="{name}"]\ntexture = {texture(source)}\ntexture_margin_left = 16.0\ntexture_margin_top = 16.0\ntexture_margin_right = 16.0\ntexture_margin_bottom = 16.0\ncontent_margin_left = 16.0\ncontent_margin_top = 12.0\ncontent_margin_right = 40.0\ncontent_margin_bottom = 12.0')
    # Replace previous property, avoiding duplicate keys in .tres.
    props = [p for p in props if not p.startswith(f'OptionButton/styles/{state} =')]
    prop("OptionButton","styles",state,f'SubResource("{name}")')
for t in ["Panel","PanelContainer","PopupPanel","PopupMenu","TabContainer"]:
    prop(t,"styles","panel",panel)
prop("PopupMenu","styles","hover",hover)
prop("PopupMenu","constants","v_separation",12)
for t in ["LineEdit","TextEdit"]:
    prop(t,"styles","normal",input_box)
    prop(t,"styles","focus",focus)
    prop(t,"colors","caret_color",gold)
    prop(t,"colors","selection_color",'Color(0.35,0.24,0.14,1)')
for t in ["HSeparator","VSeparator"]:
    prop(t,"styles","separator",separator)
for t in ["HSlider","VSlider"]:
    prop(t,"styles","slider",track)
    prop(t,"styles","grabber_area",fill)
    prop(t,"styles","grabber_area_highlight",fill)
    for icon in ["grabber","grabber_highlight","grabber_disabled"]:
        prop(t,"icons",icon,texture("grabber"))
for t in ["CheckButton","CheckBox"]:
    for state in ["normal","hover","pressed","disabled"]:
        prop(t,"styles",state,empty)
    prop(t,"styles","focus",focus)
    for name in ["checked","checked_disabled","on","on_disabled","on_mirrored"]:
        prop(t,"icons",name,texture("check_on"))
    for name in ["unchecked","unchecked_disabled","off","off_disabled","off_mirrored"]:
        prop(t,"icons",name,texture("check_off"))
for t in ["TabBar", "TabContainer"]:
    for state,box in [("tab_selected",primary),("tab_unselected",normal),("tab_hovered",hover),("tab_focus",focus),("tab_disabled",disabled)]:
        prop(t,"styles",state,box)
    prop(t, "colors", "font_selected_color", bone)
    prop(t, "colors", "font_unselected_color", muted)
    prop(t, "font_sizes", "font_size", 18)
# Explicit body font prevents check/toggle labels inheriting Button's display face.
sub.append('[sub_resource type="SystemFont" id="body_font"]\nfont_names = PackedStringArray("Noto Sans", "Arial")\nmultichannel_signed_distance_field = true')
for t in ["CheckButton", "CheckBox"]:
    prop(t, "fonts", "font", 'SubResource("body_font")')
for t in ["HScrollBar","VScrollBar"]:
    prop(t,"styles","scroll",track)
    for state in ["grabber","grabber_highlight","grabber_pressed"]:
        prop(t,"styles",state,fill)
prop("ProgressBar","styles","background",track)
prop("ProgressBar","styles","fill",fill)
(ROOT / "themes/grimdark.tres").write_text(f'[gd_resource type="Theme" load_steps={len(ext)+len(sub)+1} format=3]\n\n'+'\n'.join(ext)+'\n\n'+'\n\n'.join(sub)+'\n\n[resource]\ndefault_font = SubResource("body_font")\ndefault_font_size = 16\n'+'\n'.join(props)+'\n')
