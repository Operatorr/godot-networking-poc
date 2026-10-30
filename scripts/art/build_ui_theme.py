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
    aperture = {"health_frame": (20, 16, 490, 20), "mana_frame": (10, 16, 490, 20), "stamina_frame": (10, 6, 380, 8)}.get(name)
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

# HUD hardware: slender layered iron rails with worn gold highlights, distinct
# from the broader menu corners. Resource frames have mirrored pointed outer ends.
for kind in ["health", "mana"]:
    s = '<path d="M20 2H520V50H20L2 26Z" fill="#050708" stroke="#252828" stroke-width="2"/>'
    for inset, color in [(4,"#666052"),(6,"#252927"),(8,"#8e7954"),(10,"#121719"),(12,"#45443b")]:
        s += f'<path d="M22 {inset}H518V{52-inset}H22L{inset+3} 26Z" fill="none" stroke="{color}"/>'
    s += '<path d="M24 14H514M24 38H514" stroke="#b09a6c" stroke-opacity=".65"/><path d="M28 3H514" stroke="#c2b391" stroke-opacity=".5"/>'
    for x in range(30, 510, 29):
        s += f'<path d="M{x} 5h7M{x+9} 47h4" stroke="#a59a7b" stroke-opacity=".35"/><path d="M{x+14} 7h3M{x+4} 45h6" stroke="#0b0d0d"/>'
    for x,y in [(21,5),(8,26),(21,47)]:
        s += f'<path d="M{x} {y-3}l3 3l-3 3l-3-3Z" fill="#282b28" stroke="#ab9163"/><rect x="{x}" y="{y-1}" width="1" height="2" fill="#e5d5ad"/>'
    if kind == "mana":
        s = '<g transform="translate(520 0) scale(-1 1)">'+s+'</g>'
    svg(f"{kind}_frame", 520, 52, s)
svg("stamina_frame", 400, 20, '<path d="M5 1H395L399 5V15L395 19H5L1 15V5Z" fill="#080b0c" stroke="#67604c"/><path d="M7 3H393V17H7Z" fill="none" stroke="#b39b64"/><path d="M9 5H391V15H9Z" fill="none" stroke="#392e1d"/><path d="M10 2H390" stroke="#e2d0a0"/>')

def hud_box(w, h, transparent=False):
    s = '' if transparent else f'<rect x="4" y="4" width="{w-8}" height="{h-8}" fill="#080b0e"/>'
    for inset,col in [(1,"#050708"),(2,"#42423b"),(3,"#96805b"),(4,"#d0ba86"),(5,"#4c4432"),(7,"#171c1c"),(8,"#615339")]:
        s += f'<path d="M{inset+2} {inset}H{w-inset-2}L{w-inset} {inset+2}V{h-inset-2}L{w-inset-2} {h-inset}H{inset+2}L{inset} {h-inset-2}V{inset+2}Z" fill="none" stroke="{col}"/>'
    for x,y in [(5,5),(w-6,5),(5,h-6),(w-6,h-6)]:
        s += f'<rect x="{x-2}" y="{y-2}" width="5" height="5" fill="#4e402c"/><path d="M{x-1} {y-1}h3v2h-3Z" fill="#c4a36b"/><rect x="{x}" y="{y}" width="1" height="1" fill="#f1dab0"/>'
    for x in range(12,w-10,13):
        s += f'<path d="M{x} 3h4M{x+2} {h-4}h3" stroke="#151915"/><path d="M{x} 2h2" stroke="#e0c597"/>'
    return s

svg("slot", 60, 60, hud_box(60,60))
svg("key_badge", 48, 26, '<path d="M5 1H43L47 5V21L43 25H5L1 21V5Z" fill="#080b0c" stroke="#514735"/><path d="M6 3H42L45 6V20L42 23H6L3 20V6Z" fill="none" stroke="#ac9462"/><path d="M7 2H41" stroke="#deca95"/>')

# Map and feed share gilt corner brackets and a diamond compass ornament.
def map_frame(w,h):
    s = hud_box(w,h,True)
    for x,y,sx,sy in [(5,5,1,1),(w-5,5,-1,1),(5,h-5,1,-1),(w-5,h-5,-1,-1)]:
        s += f'<g transform="translate({x} {y}) scale({sx} {sy})"><path d="M0 0H18V5H5V18H0Z" fill="#b38337"/><path d="M1 1H17V3H3V17H1Z" fill="#eac787"/><path d="M5 6H8V9H5Z" fill="#5a4025"/></g>'
    for y in [8,h-8]:
        s += f'<path d="M{w//2} {y-7}l7 7l-7 7l-7-7Z" fill="#574123" stroke="#d4ab60"/><path d="M{w//2} {y-4}l4 4l-4 4l-4-4Z" fill="#e8c582"/><rect x="{w//2-1}" y="{y-1}" width="2" height="2" fill="#fff0c2"/>'
    return s
svg("minimap_frame",280,280,map_frame(280,280))
svg("kill_feed_frame",280,64,'<rect x="4" y="4" width="272" height="56" fill="#080b0e" fill-opacity=".94"/>'+map_frame(280,64))
svg("kill_skull",24,28,'<path d="M6 2H18V4H21V8H23V17H19V21H17V26H14V22H11V26H8V21H5V17H2V8H4V4H6Z" fill="#871723"/><path d="M7 3H17V5H20V9H21V15H18V18H16V24H14V20H10V24H9V18H6V15H4V9H5V5H7Z" fill="#ef3b45"/><path d="M6 10H10V14H6ZM15 10H19V14H15ZM11 15H14V18H11Z" fill="#21090e"/><path d="M7 4H16V6H7Z" fill="#ff8271"/>')

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
