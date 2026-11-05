"""Ocean Foundry native Windows application (Qt Widgets, no webview/server)."""
import json
import math
import os
from pathlib import Path
import sys
import traceback
import numpy as np
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF, QImage, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QTabWidget,
    QGroupBox, QFileDialog, QMessageBox, QScrollArea, QSplitter, QTextBrowser,
    QCheckBox, QColorDialog, QListWidget, QListWidgetItem)
import ocean
import colour
import mesh
import dither
from colour_preview import ColourPreviewMixin
from gpu_view import GPUView
from bake_ui import BakeMixin
import appearance
from controls import numeric_row
import control_help
import baker
import localization
import project_files
import smoke
from compass import Compass

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
STATE = ROOT / 'settings.json'


class Signals(QObject):
    done = Signal(int, object, str)


class Job(QRunnable):
    def __init__(self, token, fn):
        super().__init__()
        self.token, self.fn, self.signals = token, fn, Signals()

    def run(self):
        try:
            result, error = self.fn(), ''
        except Exception as exc:
            result, error = None, str(exc)
        self.signals.done.emit(self.token, result, error)


class Preview(QWidget):
    def __init__(self, top=False):
        super().__init__()
        self.top, self.result = top, None
        self.yaw, self.pitch, self.zoom = -.7, .75, 1.0
        self.last = None
        self.settle=QTimer(self)
        self.settle.setSingleShot(True)
        self.settle.timeout.connect(self.update)
        self.render_key=None
        self.gpu=None
        self.gpu_error=''
        if not top and QApplication.platformName() not in ('offscreen','minimal') and '--software' not in sys.argv:
            self.gpu=GPUView(self)
            self.gpu.failed.connect(self.use_software)
            QTimer.singleShot(3000,self.check_gpu)
        self.compass=Compass(self);self.compass.show()
        self.map_kind = 'height'
        self.setMinimumSize(280, 260)
        self.setMouseTracking(True)
        self.setToolTip('Drag to rotate • wheel to zoom • double-click to reset' if not top else 'Full-resolution heightmap; lighter = higher')

    def set_result(self, result):
        self.result = result
        s = result['settings']
        h = np.array(result['heights']).reshape(s['length'], s['width'])
        self.h = h
        norm = (h-h.min()) / max(1, np.ptp(h))
        low, high = np.array([20, 48, 66]), np.array([162, 238, 221])
        pixels = np.ascontiguousarray(low+(high-low)*norm[..., None], dtype=np.uint8)
        self.map = QImage(pixels.data, s['width'], s['length'], s['width']*3, QImage.Format.Format_RGB888).copy()
        if self.top: self.set_map(self.map_kind)
        if self.gpu is not None: self.gpu.set_result(result)
        self.update()

    def check_gpu(self):
        if self.gpu is not None and not self.gpu.isValid():
            self.use_software('OpenGL context unavailable')

    def use_software(self,reason):
        self.gpu_error=reason
        if self.gpu is not None:
            self.gpu.hide()
            self.gpu.deleteLater()
            self.gpu=None
        self.setToolTip('Drag to rotate • wheel to zoom • double-click to reset')
        self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.gpu is not None: self.gpu.setGeometry(self.rect())
        self.compass.move(self.width()-98,42);self.compass.raise_()

    def set_map(self,kind):
        self.map_kind=kind
        if not self.result: return
        r=self.result; s=r['settings']; w,l=s['width'],s['length']
        required={'target':'target_rgb','blocks':'block_rgb','solid':'solid_rgb','normal':'normal_rgb','foam':'foam_rgb','reflection':'reflection_rgb','depth':'depth'}
        self.map_unavailable=kind in required and required[kind] not in r
        if self.map_unavailable:self.map=QImage();self.update();return
        if kind in ('target','blocks','solid','normal','foam','reflection') and 'target_rgb' in r:
            pixels=r.get({'target':'target_rgb','solid':'solid_rgb','blocks':'block_rgb','normal':'normal_rgb','foam':'foam_rgb','reflection':'reflection_rgb'}[kind],r['block_rgb'])
        else:
            if kind=='depth' and 'depth' in r:
                # A fixed unsloped projected extent preserves visible slope strength.
                angle=math.radians(r['colour_settings']['depth_direction'])
                extent=max(1,abs(math.cos(angle))*(w-1)+abs(math.sin(angle))*(l-1))
                norm=1-r['depth']/max(128,float(r['depth'].max()))
            else:
                norm=(self.h-self.h.min())/max(1,np.ptp(self.h))
            pixels=np.array([20,48,66])+np.array([142,190,155])*norm[...,None]
        pixels=np.ascontiguousarray(pixels,dtype=np.uint8)
        self.map=QImage(pixels.data,w,l,w*3,QImage.Format.Format_RGB888).copy()
        self.update()

    def paint_mesh(self,p):
        interacting=self.last is not None or self.settle.isActive()
        key=(id(self.result),self.yaw,self.pitch,self.zoom,self.width(),self.height(),interacting)
        if self.render_key!=key:
            self.render_image=QImage(self.size(),QImage.Format.Format_RGB32)
            self.render_image.fill(QColor('#101d29'))
            painter=QPainter(self.render_image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing,not interacting)
            self.draw_mesh(painter,interacting)
            painter.end()
            self.render_key=key
        p.drawImage(0,0,self.render_image)

    def draw_mesh(self,p,interacting):
        m=self.result.get('interaction_mesh',self.result['mesh']) if interacting else self.result['mesh']
        ca,sa=math.cos(self.yaw),math.sin(self.yaw)
        cp,sp=math.cos(self.pitch),math.sin(self.pitch)
        direction=m['directions']
        visible=(direction==0)|((direction==(1 if sa>=0 else 2)))|((direction==(3 if ca>=0 else 4)))
        indices=np.flatnonzero(visible)
        centres=m['centres'][indices]
        order=np.argsort((centres[:,0]*sa+centres[:,2]*ca)*cp+centres[:,1]*sp)
        indices=indices[order]
        v=m['vertices'][indices]
        scale=min((self.width()-80)/(m['width']+m['length']),
                  (self.height()-110)/(max(m['width'],m['length'])+m['height']))*1.5*self.zoom
        xx=self.width()/2+(v[:,:,0]*ca-v[:,:,2]*sa)*scale
        yy=self.height()*.57+((v[:,:,0]*sa+v[:,:,2]*ca)*sp-v[:,:,1]*cp)*scale
        for i,index in enumerate(indices):
            rgb=m['rgb'][index]
            col=QColor(int(rgb[0]),int(rgb[1]),int(rgb[2]))
            p.setPen(col); p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(float(x),float(y)) for x,y in zip(xx[i],yy[i])]))
        p.setPen(QColor('#b6ccd9'))
        p.drawText(24,30,'Drag to orbit · Scroll to zoom · Double-click to reset')
        if interacting:
            caption='Fast orbit preview · Full detail returns when movement stops'
        elif m.get('textured'):
            caption='Preview · 2D maps and exports retain full block detail'
        else:
            caption='Preview · Exports retain full block detail'
        p.drawText(24,self.height()-24,caption)

    def mousePressEvent(self, event):
        self.last = event.position()
        self.update()

    def mouseReleaseEvent(self, event):
        self.last = None
        self.settle.start(180)
        self.update()

    def mouseMoveEvent(self, event):
        if self.last is not None and not self.top:
            d = event.position()-self.last
            self.yaw += d.x()*.008
            self.pitch = min(1.45, max(.15, self.pitch+d.y()*.006))
            self.last = event.position()
            self.update()

    def wheelEvent(self, event):
        self.zoom = min(3, max(.4, self.zoom*math.exp(event.angleDelta().y()/1200)))
        self.settle.start(180)
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.yaw, self.pitch, self.zoom = -.7, .75, 1
        self.update()

    def paintEvent(self, event):
        self.compass.update()
        if self.gpu is not None: return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#101d29'))
        if not self.result:
            p.setPen(QColor('#9fb3c4'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Generating your ocean…')
            return
        s = self.result['settings']
        w, l = s['width'], s['length']
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.top:
            scale = min((self.width()-90)/w, (self.height()-110)/l)*self.zoom
            target = QRectF((self.width()-w*scale)/2, (self.height()-l*scale)/2, w*scale, l*scale)
            p.drawImage(target, self.map)
            p.setPen(QColor('#b6ccd9'))
            p.drawText(24, 30, f'X → {w} blocks     Z ↓ {l} blocks')
            if getattr(self,'map_unavailable',False):p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Bake required for this map');p.end();return
            if self.map_kind=='depth' and 'depth' in self.result:
                angle=math.radians(self.result['colour_settings']['depth_direction'])
                centre=QPointF(self.width()-100,175)
                end=centre+QPointF(math.cos(angle)*35,math.sin(angle)*35)
                p.setPen(QColor('#ffffff')); p.drawLine(centre,end)
                for sign in [-1,1]:
                    a=angle+math.pi+sign*.5
                    p.drawLine(end,end+QPointF(math.cos(a)*12,math.sin(a)*12))
                p.drawText(self.width()-140,230,'Deeper →')
                caption=f'Simulated depth: {self.result["depth"].min():.1f}–{self.result["depth"].max():.1f} blocks · 0° = +X, 90° = +Z'
            else:
                caption={'height':'Concrete height · Lighter = higher','target':'Continuous target colour',
                    'blocks':'Approximate combined block colours','solid':'Solid block texture-average colours',
                    'normal':'Generated surface normals · independent of concrete height',
                    'foam':'Breaking foam only · reflections are separate'}.get(self.map_kind,'')
            p.drawText(24,self.height()-24,caption+' · Every column shown')
        elif 'mesh' in self.result:
            # Every generate/bake result carries a mesh; the old column fallback is gone.
            self.paint_mesh(p)
            p.end()
            return
        p.end()


class Window(BakeMixin,ColourPreviewMixin,QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Ocean Foundry')
        self.resize(1440, 940)
        self.result = None
        self.revision = 0
        self.state_path=STATE
        self.jobs = {}
        self.exporting = False
        self.controls = {}
        self.colour_controls = {}
        self.colour_values = dict(colour.DEFAULTS)
        self.init_baking()
        self.generating = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.generate)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24,18,24,18)
        header = QHBoxLayout()
        title = QLabel('OCEAN FOUNDRY')
        title.setObjectName('title')
        header.addWidget(title)
        header.addStretch()
        self.about_button=QPushButton('About')
        self.about_button.clicked.connect(lambda: QMessageBox.about(self,'About Ocean Foundry','Ocean Foundry\nVersion 1.3.1\n\nCreated by SirChocoo\nCopyright © 2026 SirChocoo'))
        save_profile=QPushButton('Save profile…');save_profile.clicked.connect(self.save_profile);header.addWidget(save_profile)
        open_profile=QPushButton('Open profile…');open_profile.clicked.connect(self.open_profile);header.addWidget(open_profile)
        self.sidebar_toggle=QPushButton('Bake sidebar');self.sidebar_toggle.setCheckable(True);self.sidebar_toggle.setChecked(True);header.addWidget(self.sidebar_toggle)
        header.addWidget(self.about_button)
        layout.addLayout(header)
        subtitle = QLabel('Shape the surface. Build the foundation. Export to your world.')
        subtitle.setObjectName('muted')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        split = QSplitter()
        layout.addWidget(split, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(280)
        scroll.setMaximumWidth(400)
        panel = QWidget()
        self.form_layout = QVBoxLayout(panel)
        scroll.setWidget(panel)
        self.control_tabs=QTabWidget()
        self.control_tabs.setMinimumWidth(300)
        self.control_tabs.setMaximumWidth(410)
        self.control_tabs.addTab(scroll,'Waves && foundation')
        split.addWidget(self.control_tabs)
        self.group('BUILD AREA', [('width','Width · X',16,1024),('length','Length · Z',16,1024),('base_y','Placement Y',-64,319)])
        self.group('WAVE SHAPE', [('wave_height','Crest-to-trough height',0,96),('wavelength','Peak spacing',8.,256.),
            ('direction','Direction · degrees',0.,360.),('irregularity','Irregularity',0.,1.),
            ('detail','Secondary swell detail',0.,1.),('sharpness','Crest choppiness',0.,1.),('seed','Seed',0,2147483647)])
        gentle=QPushButton('Use gentle foundation swells')
        gentle.clicked.connect(self.gentle_foundation)
        self.form_layout.addWidget(gentle)
        box = QGroupBox('FOUNDATION')
        f = QFormLayout(box)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for key,label,items in [('fill','Construction',[('Surface shell','shell'),('Solid to base','solid')]),
            ('block','Concrete',[(c.replace('_',' ').title(),c) for c in ocean.COLOURS])]:
            c = QComboBox()
            for text,value in items: c.addItem(text,value)
            c.setCurrentIndex(c.findData(ocean.DEFAULTS[key]))
            self.controls[key] = c
            c.currentIndexChanged.connect(self.changed)
            f.addRow(label,c)
        thick = QSpinBox()
        thick.setRange(1,16)
        thick.setValue(1)
        thick.valueChanged.connect(self.changed)
        self.controls['thickness'] = thick
        numeric_row(f,'Thickness',thick,control_help.FOUNDATION['thickness'])
        self.form_layout.addWidget(box)
        hint = QLabel('A thin shell can have gaps at steep height changes. Increase thickness or use solid fill when needed.')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        self.form_layout.addWidget(hint)
        self.form_layout.addStretch()
        self.make_colour_panel()
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)
        split.setStretchFactor(1,1)
        split.setStretchFactor(0,0)
        split.setSizes([380,850])
        self.preview, self.heightmap = Preview(), Preview(True)
        surface_page=QWidget();surface_layout=QVBoxLayout(surface_page);inspect_row=QHBoxLayout()
        self.inspect_layer=QComboBox()
        for label,key in [('Combined appearance','combined'),('Concrete','foundation'),('Solid colour','solid'),('All glass','glass'),('Glass layer 1','glass_1'),('Glass layer 2','glass_2'),('Glass layer 3','glass_3'),('Foam glass','foam')]:self.inspect_layer.addItem(label,key)
        self.cutaway=QCheckBox('Cutaway');self.inspect_layer.currentIndexChanged.connect(self.refresh_inspection);self.cutaway.toggled.connect(self.refresh_inspection)
        inspect_row.addWidget(self.inspect_layer);inspect_row.addWidget(self.cutaway);inspect_row.addStretch();surface_layout.addLayout(inspect_row)
        self.preview_stale=QLabel('Settings changed · Bake to update the block preview.');self.preview_stale.setWordWrap(True);surface_layout.addWidget(self.preview_stale)
        surface_layout.addWidget(self.preview,1)
        self.tabs.addTab(surface_page,'3D surface')
        maps=QWidget(); ml=QVBoxLayout(maps)
        self.map_mode=QComboBox()
        for name,key in [('Concrete height','height'),('Simulated depth','depth'),('Target colours','target'),('Combined block appearance','blocks'),('Solid layer colours','solid'),('Surface normals','normal'),('Reflections','reflection'),('Breaking foam / lava heat','foam')]:
            self.map_mode.addItem(name,key)
        self.map_mode.currentIndexChanged.connect(lambda: self.heightmap.set_map(self.map_mode.currentData()))
        ml.addWidget(self.map_mode); ml.addWidget(self.heightmap,1)
        self.tabs.addTab(maps,'2D maps')
        self.setup_colour_preview()
        export = QWidget()
        ef = QVBoxLayout(export)
        ef.setContentsMargins(28,28,28,28)
        ef.addWidget(QLabel('EXPORT YOUR OCEAN'))
        options = QFormLayout()
        self.version = QComboBox()
        self.version.addItems(ocean.VERSIONS)
        self.version.setCurrentText('26.1.2')
        self.format = QComboBox()
        self.format.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.format.setMinimumContentsLength(12)
        self.format.addItem('Litematica (.litematic)', '.litematic')
        self.format.addItem('WorldEdit (.schem)', '.schem')
        self.format.addItem('Axiom blueprint (.bp)', '.bp')
        options.addRow('Minecraft Java version',self.version)
        options.addRow('File format',self.format)
        self.export_layer=QComboBox()
        for key,name in [('combined','All layers'),('foundation','Concrete only'),('solid','Solid colour only'),('glass','All glass'),('glass_1','Glass layer 1'),('glass_2','Glass layer 2'),('glass_3','Glass layer 3'),('foam','Foam glass')]:
            self.export_layer.addItem(name,key)
        options.addRow('Layers',self.export_layer)
        ef.addLayout(options)
        self.omit_air=QCheckBox('Omit air in Litematica')
        self.omit_air.setChecked(True)
        self.omit_air.setToolTip('Enabled: empty space is outside all regions. Disabled: compact single region; use ignore-air placement. Large air-free builds can contain many regions.')
        self.format.currentIndexChanged.connect(lambda:self.omit_air.setVisible(self.format.currentData()=='.litematic'))
        ef.addWidget(self.omit_air)
        self.export_button = QPushButton('Save ocean…')
        self.export_button.setObjectName('primary')
        self.export_button.clicked.connect(self.export)
        ef.addWidget(self.export_button)
        self.png_button = QPushButton('Save 16-bit heightmap PNG…')
        self.png_button.clicked.connect(self.save_png)
        ef.addWidget(self.png_button)
        self.placement = QLabel()
        self.placement.setWordWrap(True)
        ef.addWidget(self.placement)
        note = QLabel('Choose one format per export. Match your mod to the selected Minecraft version.\n\nLitematica skips empty space using multiple regions; keep all regions together. Axiom also skips empty space. WorldEdit schematics require //paste -a to skip air.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        ef.addWidget(note)
        ef.addStretch()
        self.tabs.addTab(export,'Export')
        plan = QTextBrowser()
        plan.setOpenExternalLinks(False)
        path = (Path(getattr(sys,'_MEIPASS',ROOT)) / ('USER_GUIDE.zh-CN.md' if localization.LANGUAGE=='zh_CN' else 'USER_GUIDE.md'))
        plan.setMarkdown(path.read_text(encoding='utf-8') if path.exists() else 'Choose settings, then Bake and Export.')
        self.tabs.addTab(plan,'Guide')
        self.setup_bake_panel()
        self.sidebar=self.make_bake_sidebar();split.addWidget(self.sidebar)
        self.sidebar_toggle.toggled.connect(self.sidebar.setVisible)
        split.setStretchFactor(2,0)
        split.setSizes([380,700,250])
        self.status = QLabel('Preparing the surface…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.restore()
        self.autosave_timer=QTimer(self);self.autosave_timer.setSingleShot(True);self.autosave_timer.setInterval(1200);self.autosave_timer.timeout.connect(self.save_settings)
        self.control_tabs.setCurrentIndex(0)
        self.changed()

    def gentle_foundation(self):
        for key,value in dict(wave_height=12,wavelength=120,irregularity=.65,detail=.08,sharpness=.65).items():
            self.controls[key].setValue(value)

    def make_colour_panel(self):
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        panel=QWidget(); layout=QVBoxLayout(panel)
        scroll.setWidget(panel)
        self.make_bake_controls(layout)
        box=QGroupBox('BLOCK MATERIALS · JAVA 26.1.2')
        form=QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for key,label in [('enabled','Include colour and glass'),('creative','Use creative blocks')]:
            c=QCheckBox(label); c.setChecked(colour.DEFAULTS[key])
            c.toggled.connect(self.changed)
            self.colour_controls[key]=c
            form.addRow(c)
        self.colour_controls['creative'].setToolTip('Off: all compatible survival-obtainable blocks except netherite blocks and ancient debris. On: also permits those exceptions and creative-only blocks. Both modes use opaque full cubes with stable measured colours; translucent and biome-tinted blocks are not included. Falling blocks need support; functional blocks retain their game behaviour.')
        self.colour_buttons={}
        for key,label in [('dark','Water colour'),('light','Lit water colour')]:
            button=QPushButton()
            button.setMinimumHeight(36)
            button.clicked.connect(lambda checked=False,k=key:self.pick_colour(k))
            self.colour_buttons[key]=button
            self.ocean_colour_form.insertRow(0 if key=='dark' else 1,label,button)
        for key,label,lo,hi,step in [('depth_slope','Depth slope',0,1,.05),
            ('depth_direction','Deeper direction · degrees',0,360,5),
            ('texture_preference','Prefer smooth block textures',0,1,.05),('palette_size','Maximum solid block types',1,32,1)]:
            c=QSpinBox() if key=='palette_size' else QDoubleSpinBox()
            c.setRange(lo,hi); c.setSingleStep(step)
            if isinstance(c,QDoubleSpinBox): c.setDecimals(2 if hi==1 else 1)
            c.setValue(colour.DEFAULTS[key]); c.valueChanged.connect(self.changed)
            self.colour_controls[key]=c
            numeric_row(form if key in ('palette_size','texture_preference') else self.ocean_depth_form,label,c,control_help.COLOUR[key])
        layout.addWidget(box)
        dithering=QGroupBox('MATERIAL BLENDING / DITHERING')
        df=QFormLayout(dithering)
        df.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        method=QComboBox()
        for key,name in dither.METHODS.items(): method.addItem(name,key)
        method.setCurrentIndex(method.findData(colour.DEFAULTS['dither_method']))
        method.currentIndexChanged.connect(self.changed)
        self.colour_controls['dither_method']=method
        df.addRow('Method',method)
        for key,label,lo,hi in [('dither_strength','Blend strength',0.,1.),
            ('dither_grain','Pattern size · blocks',1,8),('dither_seed','Noise seed',0,2147483647)]:
            c=QDoubleSpinBox() if key=='dither_strength' else QSpinBox()
            c.setRange(lo,hi)
            if isinstance(c,QDoubleSpinBox): c.setDecimals(2); c.setSingleStep(.05)
            c.setValue(colour.DEFAULTS[key]); c.valueChanged.connect(self.changed)
            self.colour_controls[key]=c; numeric_row(df,label,c,control_help.COLOUR[key])
        note=QLabel('Mixes neighbouring palette colours to soften bands. Strength 0 keeps hard transitions. Pattern size applies to ordered/noise methods; error diffusion works one block at a time.')
        note.setWordWrap(True); note.setObjectName('muted')
        df.addRow(note)
        layout.addWidget(dithering)
        materials_box=QGroupBox('BAKED MATERIALS / REPLACEMENTS');materials_layout=QVBoxLayout(materials_box)
        self.palette_list=QListWidget(); self.palette_list.setMinimumHeight(230)
        materials_layout.addWidget(self.palette_list)
        self.replacement_choice=QComboBox()
        materials_layout.addWidget(QLabel('Replace selected material with a similar colour'))
        materials_layout.addWidget(self.replacement_choice)
        replace=QPushButton('Use replacement on next bake');replace.clicked.connect(self.replace_block);materials_layout.addWidget(replace)
        self.palette_list.currentItemChanged.connect(self.refresh_replacements)
        reset_replacements=QPushButton('Reset material replacements');reset_replacements.clicked.connect(self.reset_replacements);materials_layout.addWidget(reset_replacements)
        exclude=QPushButton('Exclude selected block')
        exclude.clicked.connect(self.exclude_block); materials_layout.addWidget(exclude)
        reset=QPushButton('Reset block exclusions')
        reset.clicked.connect(self.reset_exclusions); materials_layout.addWidget(reset)
        self.palette_status=QLabel('Bake to choose materials from the surface colours.')
        self.palette_status.setWordWrap(True); self.palette_status.setObjectName('muted')
        materials_layout.addWidget(self.palette_status)
        self.glass_status=QLabel();self.glass_status.setWordWrap(True);materials_layout.addWidget(self.glass_status)
        layout.addWidget(materials_box)
        layout.addStretch()
        self.control_tabs.addTab(scroll,'Colour && glass')
        self.refresh_colour_buttons()

    def refresh_colour_buttons(self):
        for key,button in self.colour_buttons.items():
            value=self.colour_values[key]
            rgb=QColor(value)
            foreground='#10202a' if rgb.lightnessF()>.55 else '#ffffff'
            button.setText(value.upper())
            button.setStyleSheet(f'background: {value}; color: {foreground}; padding: 9px;')

    def refresh_replacements(self,*args):
        self.replacement_choice.clear();item=self.palette_list.currentItem()
        if item is None:return
        for block,distance in colour.similar_blocks(item.data(Qt.ItemDataRole.UserRole),self.colour_settings()):
            self.replacement_choice.addItem(block['id'].removeprefix('minecraft:').replace('_',' ').title(),block['id'])
            idx=self.replacement_choice.count()-1
            self.replacement_choice.setItemData(idx,QColor(*map(int,block['top_rgb'])),Qt.ItemDataRole.BackgroundRole)

    def replace_block(self):
        item=self.palette_list.currentItem();target=self.replacement_choice.currentData()
        if item is None or target is None:return
        source=item.data(Qt.ItemDataRole.UserRole)
        replacements=dict(self.colour_values.get('block_replacements',{}))
        origins=[b['id'] for b in self.result.get('automatic_blocks',[]) if replacements.get(b['id'],b['id'])==source]
        for origin in origins or [source]:
            eligible={b['id'] for b,_ in colour.similar_blocks(origin,self.colour_settings(),1000)}
            if target not in eligible:
                self.status.setText('Replacement is too different from the original automatic material. Reset replacements first.');return
        for origin in origins or [source]:
            if target==origin:replacements.pop(origin,None)
            else:replacements[origin]=target
        self.colour_values['block_replacements']=replacements;self.changed()

    def reset_replacements(self):
        self.colour_values['block_replacements']={};self.changed()

    def pick_colour(self,key):
        original=self.colour_values[key]
        dialog=QColorDialog(QColor(original),self)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog,True)
        dialog.setWindowTitle('Choose '+('lit water' if key=='light' else 'water')+' colour')
        def apply(value):
            if value.isValid():
                self.colour_values[key]=value.name()
                self.refresh_colour_buttons()
                self.changed()
        dialog.currentColorChanged.connect(apply)
        if not dialog.exec(): apply(QColor(original))

    def exclude_block(self):
        item=self.palette_list.currentItem()
        if item:
            self.colour_values['excluded']=sorted(set(self.colour_values['excluded']+[item.data(Qt.ItemDataRole.UserRole)]))
            self.changed()

    def reset_exclusions(self):
        self.colour_values['excluded']=[]
        self.changed()

    def colour_settings(self):
        return {**self.colour_values,**{k:c.isChecked() if isinstance(c,QCheckBox) else c.currentData() if isinstance(c,QComboBox) else c.value()
            for k,c in self.colour_controls.items()}}

    def result_current(self):
        return (self.result is not None and self.result['settings']==self.settings()
            and self.result.get('colour_settings')==colour.validate(self.colour_settings())
            and (not self.colour_controls['enabled'].isChecked() or
                 self.result.get('appearance_settings')==self.appearance_settings()))

    def group(self, title, fields):
        box = QGroupBox(title)
        f = QFormLayout(box)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for key,label,lo,hi in fields:
            c = QDoubleSpinBox() if isinstance(lo,float) else QSpinBox()
            c.setRange(lo,hi)
            if isinstance(c,QDoubleSpinBox):
                c.setDecimals(2 if hi == 1 else 1)
                c.setSingleStep(.05 if hi == 1 else 1)
            c.setValue(ocean.DEFAULTS[key])
            self.controls[key] = c
            c.valueChanged.connect(self.changed)
            numeric_row(f,label,c,control_help.FOUNDATION[key])
        self.form_layout.addWidget(box)

    def settings(self):
        return {k:c.currentData() if isinstance(c,QComboBox) else c.value() for k,c in self.controls.items()}

    def restore(self,saved_path=None):
        saved_path=Path(saved_path) if saved_path else STATE if STATE.exists() else ROOT/'default_settings.json'
        if not saved_path.exists(): return
        try:
            saved = json.loads(saved_path.read_text(encoding='utf-8'))
            data = ocean.validate(saved.get('settings',saved))
            for k,v in data.items():
                c = self.controls[k]
                if isinstance(c,QComboBox): c.setCurrentIndex(c.findData(v))
                else: c.setValue(v)
            saved_colour=colour.validate(saved.get('colour',{}))
            self.colour_values=saved_colour
            self.load_bake_history(saved.get('bake_history',[]))
            for k,c in self.colour_controls.items():
                if isinstance(c,QCheckBox): c.setChecked(saved_colour[k])
                elif isinstance(c,QComboBox): c.setCurrentIndex(c.findData(saved_colour[k]))
                else: c.setValue(saved_colour[k])
            self.refresh_colour_buttons()
            migrated={}
            if 'appearance' not in saved:
                source=np.array(colour.hex_rgb(saved_colour['light']))
                for key,amount in [('crest',.35),('foam_colour',.82)]:
                    migrated[key]='#'+''.join(f'{int(v):02x}' for v in np.round(source*(1-amount)+255*amount))
            self.appearance_values=appearance.validate(appearance.water_depth.migrate(saved.get('appearance',migrated),saved_colour,data))
            if self.appearance_values['link_scale']:
                self.appearance_values['ripple_scale']=min(256,max(4,data['wavelength']*self.appearance_values['scale_ratio']))
            if self.appearance_values['link_direction']:self.appearance_values['wind_direction']=data['direction']
            self.active_mode='lava' if self.appearance_values['surface_model']=='lava' else 'ocean'
            self.load_generation_profiles(saved.get('generation_profiles',{}))
            self.mode_settings={}
            for mode,entry in saved.get('mode_settings',{}).items():
                if mode in ('ocean','lava'):
                    self.mode_settings[mode]=dict(colour=colour.validate(entry['colour']),appearance=appearance.validate(appearance.water_depth.migrate(entry['appearance'],colour.validate(entry['colour']),data)))
            self.apply_material_settings(dict(colour=saved_colour,appearance=self.appearance_values))
            if saved.get('minecraft_version') in ocean.VERSIONS: self.version.setCurrentText(saved['minecraft_version'])
            idx = self.format.findData(saved.get('format','.litematic'))
            if idx >= 0: self.format.setCurrentIndex(idx)
            self.omit_air.setChecked(saved.get('omit_air',True))
        except (ValueError,KeyError,OSError,TypeError):
            QMessageBox.warning(self,'Settings','Saved settings could not be loaded. Defaults will be used; your file is unchanged until you close the app.')

    def changed(self, *args):
        self.revision += 1
        if hasattr(self,'autosave_timer') and not getattr(self,'loading_profile',False):self.autosave_timer.start()
        if not hasattr(self,'export_button'): return
        if self.baking: return
        if self.colour_controls['enabled'].isChecked():
            self.version.setCurrentText('26.1.2')
        self.version.setEnabled(not self.colour_controls['enabled'].isChecked())
        method=self.colour_controls['dither_method'].currentData()
        self.colour_controls['dither_strength'].setEnabled(method!='none')
        self.colour_controls['dither_grain'].setEnabled(method in ('ordered','noise'))
        self.colour_controls['dither_seed'].setEnabled(method=='noise')
        self.export_button.setEnabled(False)
        self.png_button.setEnabled(False)
        imported=self.appearance_controls['normal_source'].currentData()=='imported'
        lava=self.active_mode=='lava';library=not lava and not imported and self.appearance_controls['surface_model'].currentData()=='ocean_maps'
        generated=not lava and not imported and not library
        lua=generated and self.appearance_controls['surface_model'].currentData()=='lua_waves'
        fft=generated and self.appearance_controls['surface_model'].currentData()=='fft_normals'
        def row(widget,visible):
            widget.row_widget.setVisible(visible);widget.row_label.setVisible(visible)
        row(self.appearance_controls['foam_style'],generated)
        self.import_normal_label.setVisible(imported)
        self.import_normal_button.setVisible(imported)
        self.sync_surface_source()
        self.appearance_controls['ocean_pattern'].setVisible(library);self.ocean_baseline_label.setVisible(library)
        self.import_normal_label.setText(self.appearance_values.get('normal_map_name') or 'No map selected · Import an RGB normal image')
        self.appearance_controls['normal_source'].setItemText(0,'Supplied lava maps' if lava else 'Generated ocean normals')
        self.appearance_controls['lava_pattern'].setVisible(lava and not imported);self.baseline_label.setVisible(lava and not imported)
        for key,visible in [('normal_rotation',lava or library or imported),('ripple_scale',generated),('imported_span',(imported or library) and not lava),('lava_scale',lava),('lava_distortion',lava)]:row(self.appearance_controls[key],visible)
        self.appearance_controls['imported_flip_y'].setVisible((imported or library) and not lava)
        self.appearance_controls['imported_flip_y'].setText('Reverse detected normal Y convention')
        self.appearance_controls['imported_span'].row_label.setText('Map span · blocks' if library else 'Imported map span · blocks')
        self.appearance_controls['lava_flip_y'].setVisible(lava)
        self.lava_box.setVisible(lava)
        self.appearance_controls['lava_sampling'].setVisible(lava);self.lava_sampling_label.setVisible(lava)
        for key in ('swell_strength','swell_scale'):row(self.appearance_controls[key],generated and not lua)
        row(self.appearance_controls['foundation_normals'],generated and not lua)
        self.appearance_controls['wind'].row_label.setText('Wind / foam activity' if (imported or library) and not lava else 'Wind / roughness')
        self.appearance_controls['normal_rotation'].row_label.setText('Shared direction offset · degrees' if (imported or library) and not lava else 'Map rotation · degrees')
        row(self.appearance_controls['depth_refraction'],generated and not lua)
        linked_direction=self.appearance_controls['link_direction'].isChecked()
        linked_scale=self.appearance_controls['link_scale'].isChecked()
        self.appearance_controls['link_scale'].setVisible(generated)
        row(self.appearance_controls['scale_ratio'],generated and linked_scale)
        self.appearance_controls['link_direction'].setVisible(generated)
        row(self.appearance_controls['wind_direction'],generated and not linked_direction)
        self.appearance_controls['ripple_scale'].setEnabled(not (generated and linked_scale))
        for box in (self.ocean_waves_box,self.ocean_colours_box,self.ocean_depth_box,self.water_lighting_box,self.foam_box):box.setVisible(not lava)
        for key in ('choppiness','breakup','peak_enhancement','ripple_ratio','micro_detail'):
            relevant=fft if key in ('choppiness','peak_enhancement','ripple_ratio') else generated
            row(self.appearance_controls[key],relevant)
            self.appearance_controls[key].setEnabled(relevant)
        ripples=fft and self.appearance_controls['micro_detail'].value()>0
        self.appearance_controls['ripple_ratio'].setEnabled(ripples)
        self.wave_hint.setVisible(generated)
        self.ocean_waves_box.setTitle('FFT OCEAN WAVES' if fft else 'PROCEDURAL WAVE GROUPS' if generated else 'SURFACE ROUGHNESS')
        self.wave_hint.setText('Colour preview updates automatically. Small-ripple size needs nonzero ripple strength.' if fft else 'Overlapping wave trains. Size, spread and small-detail strength shape the normals. Colour preview updates automatically.')
        for key in ('dither_strength','dither_grain','dither_seed'):
            visible=method!='none' if key=='dither_strength' else method in ('ordered','noise') if key=='dither_grain' else method=='noise'
            row(self.colour_controls[key],visible)
        a=self.appearance_settings();link_scale=generated and a['link_scale']
        base=min(256,max(4,self.settings()['wavelength']*a['scale_ratio'])) if link_scale else a['ripple_scale']
        self.appearance_controls['depth_colour_reach'].setEnabled(a['lit_strength']>0 and a['depth_colour_influence']>0)
        self.appearance_controls['shadow_softness'].setEnabled(a['lit_strength']>0 and a['shading_strength']>0)
        for key in ('shading_contrast','shading_midpoint'):self.appearance_controls[key].setEnabled(a['lit_strength']>0 and a['shading_strength']>0)
        for key in ('depth_colour_influence','shading_strength'):self.appearance_controls[key].setEnabled(a['lit_strength']>0)
        near=min(1,a['lit_strength']*(1+a['depth_colour_influence']))
        self.colour_effect_info.setText(f'Fully lit tint: {a["lit_strength"]:.0%} in deep water; up to {near:.0%} at zero depth. Extra depth tint ends at {a["depth_colour_reach"]:g} blocks. Reflection and foam overlay this.')
        span=a['depth_mode']=='span'
        row(self.appearance_controls['depth_rise'],span)
        row(self.colour_controls['depth_slope'],not span)
        dims=self.settings();dc=self.colour_settings()
        corners_x=np.array([0,dims['width']-1,0,dims['width']-1],np.float32)
        corners_z=np.array([0,0,dims['length']-1,dims['length']-1],np.float32)
        depths=appearance.depth_field(corners_x,corners_z,dims['width'],dims['length'],dc,a)
        self.depth_info.setText(f'Depth: {depths.min():.1f}–{depths.max():.1f} blocks · 0° = +X, 90° = +Z'+(' · Shallow edge reaches zero' if depths.min()==0 else ''))
        if not generated:
            self.direction_info.setText(f'Foundation direction: {a["wind_direction"]:.1f}° · Map offset: {a["normal_rotation"]:.1f}° · Effective: {(a["wind_direction"]+a["normal_rotation"])%360:.1f}°')
        elif a['link_direction']:
            self.direction_info.setText(f'Foundation wave direction: {a["wind_direction"]:.1f}°')
        else:
            self.direction_info.setText(f'Foundation direction: {dims["direction"]:.1f}° · Wave direction: {a["wind_direction"]:.1f}°')
        if (imported or library) and not lava:
            self.direction_info.setText(f'Shared foundation / map / wind direction: {appearance.wave_heading(dims,a):.1f}°\nSource wave axis aligned automatically.')
        note=' · linked to peak spacing' if link_scale else ''
        self.surface_scale_info.setText(f'Wave size: {base:.1f} blocks{note}. Depth changes crest prominence and breaking without zooming the pattern.')
        if (imported or library) and not lava:self.surface_scale_info.setText('Source normals preserved inside translated patches; narrow joins are blended. Wind changes foam, not the source shape.')
        if lava:self.surface_scale_info.setText('Source maps supply the pattern; foundation sets its direction.')
        if hasattr(self,'normal_caption'):
            key=('imported',a['normal_map_path']) if imported else ('lava',a['lava_pattern']) if lava else ('ocean_maps',a['ocean_pattern']) if library else ('ocean',a['surface_model'])
            if key!=getattr(self,'source_preview_key',None):self.show_source_normal()
            elif getattr(self,'thumbnail_baked',False):self.normal_caption.setText('Last baked normals · settings changed')
        self.bake_button.setEnabled(self.colour_controls['enabled'].isChecked() and not self.generating and not self.exporting)
        self.bake_state.setText('Unbaked changes · Press Bake to apply colour and glass settings.')
        self.status.setText('Unbaked changes · Previous colour result is not current.')
        self.preview_stale.setVisible(bool(self.result and self.result.get('procedural')))
        self.refresh_mode_visibility()
        self.schedule_colour_preview()
        if self.result is None or self.result['settings']!=self.settings() or self.result.get('geometry_settings',self.result['settings'])!=appearance.foundation_settings(self.settings(),a) or not self.colour_controls['enabled'].isChecked():
            self.timer.start(250)

    def run_job(self, token, fn, callback):
        job = Job(token,fn)
        self.jobs[id(job)] = job
        job.signals.done.connect(callback)
        job.signals.done.connect(lambda *_: self.jobs.pop(id(job),None))
        self.pool.start(job)

    def generate(self):
        if self.generating or self.baking: return
        settings = self.settings()
        geometry_settings=appearance.foundation_settings(settings,self.appearance_settings())
        colour_settings=self.colour_settings()
        try:
            ocean.validate(settings)
            colour.validate(colour_settings)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.generating=True
        self.bake_button.setEnabled(False)
        def compute():
            result={**ocean.generate(geometry_settings),'colour_settings':{**colour_settings,'enabled':False},'settings':settings,'geometry_settings':geometry_settings}
            result['mesh']=mesh.build(result)
            result['gpu_vertices']=mesh.triangle_data(result['mesh'])
            if 'voxels' in result: result['interaction_mesh']=mesh.simplified(result,32)
            return result
        self.run_job(self.revision,compute,self.generated)

    def generated(self, token, result, error):
        self.generating=False
        if token != self.revision:
            if not self.timer.isActive(): QTimer.singleShot(0,self.generate)
            return
        if error:
            self.status.setText('Generation failed: '+error)
            self.bake_button.setEnabled(self.colour_controls['enabled'].isChecked())
            return
        self.result = result
        self.preview.set_result(result)
        if hasattr(self,'inspect_layer'):
            self.inspect_layer.blockSignals(True);self.inspect_layer.setCurrentIndex(0);self.inspect_layer.blockSignals(False)
            self.cutaway.blockSignals(True);self.cutaway.setChecked(False);self.cutaway.blockSignals(False)
        self.heightmap.set_result(result)
        s,st = result['settings'],result['stats']
        self.status.setText(f'{s["width"]} × {s["length"]} wave area   /   {st["blocks"]:,} total blocks   /   {st.get("coating_blocks",0):,} coating blocks   /   Ready')
        self.palette_list.clear()
        self.refresh_bake_sidebar(result)
        if 'voxels' in result:
            height,length,width=result['voxels'].shape
            width-=2;length-=2
            self.placement.setText(f'Export bounds: {width} × {height} × {length} (X/Y/Z). Place origin at Y {s["base_y"]}.\nAll layers share X/Z 0. Litematica skips air; WorldEdit: //paste -a.\nIncludes {st.get("glass_blocks",0):,} glass blocks. Combined preview approximates glass colour filtering.')
            for block,count in zip(result['selected_blocks'],result['selected_counts']):
                if not count:continue
                item=QListWidgetItem(f'{block["id"].removeprefix("minecraft:").replace("_"," ").title()}  ·  {count:,}')
                item.setData(Qt.ItemDataRole.UserRole,block['id'])
                rgb=block['top_rgb']; col=QColor(*map(int,rgb))
                item.setBackground(col); item.setForeground(QColor('#101820' if col.lightnessF()>.55 else '#ffffff'))
                item.setToolTip(block['id']+'\n'+json.dumps(block['properties'])+('\nSurvival obtainable' if block['survival_friendly'] else '\nCreative / netherite exception'))
                self.palette_list.addItem(item)
            self.palette_status.setText(f'{len(result["selected_blocks"])} block types · {len(self.colour_values["excluded"])} excluded\nLighting, shaders and resource packs can change the in-game appearance.')
            glass_names=[key.removeprefix('minecraft:').replace('_stained_glass','').replace('_',' ') for key,count in result.get('glass_counts',{}).items() if count]
            self.glass_status.setText('Stained glass: '+', '.join(glass_names))
        else:
            self.placement.setText(f'Foundation only: {s["width"]} × {st["height"]} × {s["length"]}. Place origin at Y {s["base_y"]}.')
            self.palette_status.setText('Solid colour layer disabled.')
            self.glass_status.clear()
        self.export_button.setEnabled(not self.exporting and self.result_current())
        self.export_layer.setEnabled(bool(result.get('procedural')))
        self.bake_button.setEnabled(self.colour_controls['enabled'].isChecked() and not self.exporting)
        if not result.get('procedural') and self.colour_controls['enabled'].isChecked():
            self.status.setText('Concrete ready · Set water colours, then press Bake.')
        self.png_button.setEnabled(True)

    def refresh_inspection(self):
        if not self.result or not self.result.get('procedural') or self.baking:return
        mode=self.inspect_layer.currentData();cut=self.cutaway.isChecked();result=self.result
        if mode=='combined' and not cut:self.preview.set_result(result);return
        token=self.revision
        def ready(revision,view,error):
            if revision==self.revision and result is self.result and mode==self.inspect_layer.currentData() and cut==self.cutaway.isChecked():
                if error:self.status.setText('Inspection failed: '+error)
                else:self.preview.set_result(view)
        self.run_job(token,lambda:baker.inspection(result,mode,cut),ready)

    def export(self):
        if not self.result_current(): return
        ext = self.format.currentData()
        name,_ = QFileDialog.getSaveFileName(self,'Save ocean',str(ROOT/('ocean'+ext)),f'Minecraft build (*{ext})')
        if not name: return
        path = Path(name)
        if path.suffix.lower() != ext: path = Path(str(path)+ext)
        if str(path) != name and path.exists():
            if QMessageBox.question(self,'Replace file',f'Replace {path.name}?') != QMessageBox.StandardButton.Yes: return
        result,version = self.result,self.version.currentText()
        selected_layer=self.export_layer.currentData()
        omit_air=self.omit_air.isChecked()
        self.exporting = True
        self.export_button.setEnabled(False)
        self.status.setText('Writing ocean…')
        def write():
            export_result=baker.layer(result,selected_layer) if result.get('procedural') else result
            payload = ocean.litematic(export_result,version,omit_air=omit_air) if ext=='.litematic' else {'.schem':ocean.schematic,'.bp':ocean.blueprint}[ext](export_result,version)
            temp = path.with_name(path.name+'.tmp')
            temp.write_bytes(payload)
            os.replace(temp,path)
            return str(path)
        self.run_job(-1,write,self.exported)

    def exported(self, token, path, error):
        self.exporting = False
        self.export_button.setEnabled(self.result_current() and not self.timer.isActive())
        self.status.setText('Export failed: '+error if error else 'Saved '+path)
        if error: QMessageBox.critical(self,'Export failed',error)

    def save_png(self):
        if self.result is None or self.result['settings'] != self.settings(): return
        name,_ = QFileDialog.getSaveFileName(self,'Save heightmap',str(ROOT/'heightmap.png'),'PNG (*.png)')
        if name:
            try: Path(name).write_bytes(ocean.heightmap_png(self.result))
            except OSError as exc: QMessageBox.critical(self,'Save failed',str(exc))

    def closeEvent(self, event):
        if self.baking:
            self.cancel_bake();self.status.setText('Cancelling bake; close again when cancellation finishes.');event.ignore();return
        if self.jobs:
            self.status.setText('Please wait for the current calculation or export before closing.')
            event.ignore()
            return
        self.timer.stop()
        if hasattr(self,'colour_preview_timer'):self.stop_colour_preview()
        if any(flag in sys.argv for flag in ('--smoke-test','--gpu-smoke-test','--bake-smoke-test')):
            event.accept()
            return
        self.save_settings()
        if hasattr(self,'autosave_timer'):self.autosave_timer.stop()
        event.accept()

    def settings_snapshot(self):
        return dict(settings=ocean.validate(self.settings()),colour=colour.validate(self.colour_settings()),appearance=self.appearance_settings(),minecraft_version=self.version.currentText(),format=self.format.currentData(),omit_air=self.omit_air.isChecked(),bake_history=self.bake_history,mode_settings=self.capture_material_mode(),generation_profiles=self.generation_profiles)

    def save_settings(self):
        if any(flag in sys.argv for flag in ('--smoke-test','--gpu-smoke-test','--bake-smoke-test')):return
        if self.baking:return
        try:
            snapshot=self.settings_snapshot();temp=self.state_path.with_suffix('.tmp')
            temp.write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
            if self.state_path.exists():
                backup=self.state_path.with_suffix('.bak');backup.write_bytes(self.state_path.read_bytes())
            os.replace(temp,self.state_path)
        except (ValueError,OSError) as exc:self.status.setText('Settings not saved: '+str(exc))

    def save_profile(self):
        if self.baking:return
        name,_=QFileDialog.getSaveFileName(self,'Save profile',str(ROOT/'ocean.ofprofile'),'Ocean Foundry profile (*.ofprofile)')
        if name:
            try:project_files.write(name,self.settings_snapshot());self.status.setText('Profile saved')
            except (ValueError,OSError) as exc:QMessageBox.warning(self,'Profile',str(exc))

    def open_profile(self):
        if self.baking or self.jobs:return
        name,_=QFileDialog.getOpenFileName(self,'Open profile',str(ROOT),'Ocean Foundry profile (*.ofprofile)')
        if not name:return
        temp=STATE.with_suffix('.profile-tmp')
        try:
            values=project_files.read(name,ROOT/'normal_maps')
            ocean.validate(values['settings']);colour.validate(values['colour']);appearance.validate(values['appearance'])
            temp.write_text(json.dumps(values),encoding='utf-8');self.loading_profile=True
            self.restore(temp)
        except (ValueError,OSError,KeyError) as exc:QMessageBox.warning(self,'Profile',str(exc))
        finally:
            self.loading_profile=False
            if temp.exists():temp.unlink()
        self.changed()



STYLE = '''
QWidget { background: #142331; color: #e4edf3; font: 10pt "Segoe UI"; }
QLabel#title { font: 22pt "Segoe UI Semibold"; color: #84dfcf; }
QLabel#muted { color: #9bb0bf; }
QGroupBox { border: 1px solid #354857; border-radius: 8px; margin-top: 15px; padding: 14px 9px 9px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #84dfcf; }
QSpinBox, QDoubleSpinBox, QComboBox { background: #203443; border: 1px solid #476171; border-radius: 4px; padding: 5px; min-width: 98px; }
QPushButton { background: #294454; border: 1px solid #476171; border-radius: 5px; padding: 9px; }
QPushButton:hover { background: #365a6d; }
QPushButton:disabled { color: #768996; background: #20323f; }
QPushButton#primary { background: #28786f; font-weight: bold; }
QTabBar::tab { background: #203443; padding: 12px 18px; }
QTabBar::tab:selected { color: #91f2df; background: #304b5b; }
QTabWidget::pane { border: 1px solid #354857; }
QScrollArea { border: none; }
QTextBrowser { padding: 24px; border: none; }
QToolTip { background: #203443; color: white; border: 1px solid #476171; }
'''


def main():
    application = QApplication(sys.argv)
    localization.install(application,ROOT)
    for filename in ['segoeui.ttf','seguisb.ttf']:
        font_path = Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/filename
        if font_path.exists(): QFontDatabase.addApplicationFont(str(font_path))
    application.setStyle('Fusion')
    application.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if smoke.enabled():
        smoke.start(application, window)
    return application.exec()


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        (ROOT/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise
