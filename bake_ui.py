"""Explicit bake state, cancellable worker and timed draft presentation."""
import threading
import time
import copy
import sys
from pathlib import Path
import normal_maps
from datetime import datetime
import numpy as np
from PySide6.QtCore import Qt,QTimer,QEvent,QRectF
from PySide6.QtGui import QPainter,QColor,QImage,QOffscreenSurface,QSurfaceFormat
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLabel,QPushButton,QProgressBar,
    QGroupBox,QCheckBox,QComboBox,QDoubleSpinBox,QSpinBox,QColorDialog,QApplication,QListWidget,QFileDialog,QMessageBox,QScrollArea)
import appearance
from controls import numeric_row,LabelHelp
import control_help
import baker
import colour
import ocean


class DraftCanvas(QWidget):
    def __init__(self):
        super().__init__(); self.image=None; self.draft=False; self.setMinimumHeight(160)
    def paintEvent(self,event):
        p=QPainter(self); p.fillRect(self.rect(),QColor('#283039'))
        if self.image is not None and not self.image.isNull():
            size=self.image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            target=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            p.setOpacity(1 if self.draft else .25); p.drawImage(target,self.image)
        p.end()


class BakePanel(QWidget):
    def __init__(self,parent,cancel):
        super().__init__(parent); self.setStyleSheet('BakePanel { background: #283039; }')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,24)
        title=QLabel('BAKING SURFACE · DRAFT PREVIEW');title.setStyleSheet('font-size: 18px; font-weight: bold;')
        layout.addWidget(title)
        self.stage=QLabel();self.stage.setWordWrap(True);layout.addWidget(self.stage)
        self.bar=QProgressBar();layout.addWidget(self.bar)
        self.canvas=DraftCanvas();layout.addWidget(self.canvas,1)
        self.elapsed=QLabel();layout.addWidget(self.elapsed)
        self.cancel=QPushButton('Cancel bake');self.cancel.clicked.connect(cancel);layout.addWidget(self.cancel)
        self.parent().installEventFilter(self);self.hide()
    def eventFilter(self,obj,event):
        if obj==self.parent() and event.type()==QEvent.Type.Resize: self.setGeometry(obj.rect())
        return super().eventFilter(obj,event)


class BakeMixin:
    # Pattern controls are independent; material colours, depth and lighting are shared.
    GENERATION_KEYS=('lava_heat_mode','lava_sampling','swell_strength','swell_scale','foundation_normals','normal_rotation','ripple_scale','imported_span','normal_strength','seed','wind',
        'choppiness','breakup','peak_enhancement','ripple_ratio','micro_detail','foam_style',
        'invert_normals','imported_flip_y','normal_map_path','normal_map_name',
        'ocean_pattern','lava_pattern','lava_scale','lava_distortion','lava_flip_y',
        'link_scale','scale_ratio','link_direction','wind_direction')

    def init_baking(self):
        self.appearance_values=dict(appearance.DEFAULTS); self.appearance_controls={};self.appearance_buttons={}
        self.baking=False;self.bake_cancel=None;self.bake_latest=None;self.bake_lock=threading.Lock()
        self.bake_surface=None;self.bake_history=[]
        self.active_mode="ocean";self.mode_settings={}
        self.generation_profiles={};self.active_generation='ocean:fft_normals'
        self._visibility_signature=None

    def make_bake_controls(self,layout):
        self.bake_button=QPushButton('Bake surface colours + glass');self.bake_button.setObjectName('primary')
        self.bake_button.clicked.connect(self.start_bake)
        self.bake_state=QLabel('Unbaked changes · Press Bake to apply.')
        self.bake_state.setWordWrap(True);self.bake_state.setMinimumHeight(65)
        def group(title):
            box=QGroupBox(title);form=QFormLayout(box)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);layout.addWidget(box)
            return box,form
        def checkbox(key,label,target):
            b=QCheckBox(label);b.setChecked(appearance.DEFAULTS[key]);b.toggled.connect(self.changed)
            self.appearance_controls[key]=b;target.addRow(b)
        def number(key,label,lo,hi,step,target):
            widget=QSpinBox() if key in ('seed','glass_layers') else QDoubleSpinBox()
            widget.setRange(lo,hi);widget.setSingleStep(step)
            if isinstance(widget,QDoubleSpinBox):widget.setDecimals(2 if hi<=2 else 1)
            widget.setValue(appearance.DEFAULTS[key]);widget.valueChanged.connect(self.changed)
            numeric_row(target,label,widget,control_help.APPEARANCE[key]);self.appearance_controls[key]=widget
        def color(key,label,target):
            b=QPushButton();b.clicked.connect(lambda checked=False,k=key:self.pick_appearance_colour(k))
            self.appearance_buttons[key]=b;target.addRow(label,b)
        _,form=group('MODE / NORMAL SOURCE')
        self.material_mode=QComboBox();self.material_mode.addItem('Ocean mode','ocean');self.material_mode.addItem('Lava mode','lava')
        self.material_mode.currentIndexChanged.connect(self.switch_material_mode);form.addRow(self.material_mode)
        source=QComboBox();source.addItem('Generated ocean normals','built_in');source.addItem('Imported normal map','imported')
        source.currentIndexChanged.connect(self.switch_generation);self.appearance_controls['normal_source']=source;source.setParent(self);source.hide()
        model=QComboBox();model.addItem('FFT ocean normals','fft_normals');model.addItem('Procedural wave groups','procedural');model.addItem('Lua wave model','lua_waves');model.addItem('Ocean normal library','ocean_maps')
        model.currentIndexChanged.connect(self.switch_generation)
        self.appearance_controls['surface_model']=model
        model.setParent(self);model.hide()
        self.surface_source=QComboBox();form.addRow('Normal source',self.surface_source)
        self.surface_source.currentIndexChanged.connect(self.select_surface_source)
        baseline=QComboBox()
        for key,name in appearance.lava_surface.BASELINES:baseline.addItem(name,key)
        baseline.currentIndexChanged.connect(self.changed);self.appearance_controls['lava_pattern']=baseline
        form.addRow('Lava baseline',baseline);self.baseline_label=form.labelForField(baseline)
        ocean_baseline=QComboBox()
        for key,name in appearance.ocean_library.BASELINES:ocean_baseline.addItem(name,key)
        ocean_baseline.currentIndexChanged.connect(self.changed);self.appearance_controls['ocean_pattern']=ocean_baseline
        form.addRow('Ocean normal map',ocean_baseline);self.ocean_baseline_label=form.labelForField(ocean_baseline)
        self.import_normal_button=QPushButton('Import normal map…');self.import_normal_button.clicked.connect(self.import_normal_map);form.addRow(self.import_normal_button)
        self.import_normal_label=QLabel();self.import_normal_label.setWordWrap(True);form.addRow(self.import_normal_label)
        _,form=group('SURFACE PATTERN')
        self.direction_info=QLabel();self.direction_info.setWordWrap(True);form.addRow(self.direction_info)
        for args in [('ripple_scale','Main wave size · blocks',4,256,1),('imported_span','Imported map span · blocks',32,1024,16),
            ('normal_rotation','Map rotation · degrees',0,360,1),('lava_scale','Map span · blocks',32,1024,16),('normal_strength','Normal strength',0,2,.05),
            ('seed','Pattern seed',0,2147483647,1),('lua_layers','Lua wave layers',1,8,1),('wave_spacing','Wave spacing',.5,2,.05),('lava_distortion','Flow distortion',0,1,.05)]:number(*args,form)
        checkbox('link_scale','Link wave size to peak spacing',form)
        number('scale_ratio','Wave size / peak spacing',.05,1,.01,form)
        checkbox('link_direction','Link wave direction to foundation',form)
        number('wind_direction','Wave direction · degrees',0,360,5,form)
        self.appearance_controls['link_scale'].setToolTip('When enabled, the generated wave size follows the foundation peak spacing using the ratio below.')
        self.appearance_controls['link_direction'].setToolTip('When enabled, generated waves follow the foundation direction. Disable to set an independent wave heading; maps and Lava always share the foundation heading.')
        sampling=QComboBox();sampling.addItem('Classic · Overlapping patches','legacy');sampling.addItem('Experimental A · Contrast-preserving sampling','stochastic');sampling.addItem('Experimental B · Content-aware quilting','quilt')
        sampling.currentIndexChanged.connect(self.changed);self.appearance_controls['lava_sampling']=sampling
        form.addRow('Lava extension',sampling);self.lava_sampling_label=form.labelForField(sampling)
        checkbox('imported_flip_y','Flip imported green channel',form)
        checkbox('lava_flip_y','Flip map green channel',form)
        checkbox('invert_normals','Invert normal map / light–dark',form)
        self.appearance_controls['invert_normals'].setToolTip('Reverse normal-derived lighting using your selected colours. In lava, exchanges molten and cooled regions. Apply with Bake.')
        self.surface_scale_info=QLabel();self.surface_scale_info.setWordWrap(True);self.surface_scale_info.setObjectName('muted');form.addRow(self.surface_scale_info)
        self.ocean_waves_box,form=group('OCEAN WAVES')
        for args in [('wind','Wind / roughness',0,1,.05),('choppiness','Crest choppiness',0,1,.05),
            ('swell_strength','Swell strength',0,1,.05),('swell_scale','Swell wavelength · blocks',16,256,4),('foundation_normals','Foundation slope influence',0,1,.05),
            ('breakup','Directional spread',0,1,.05),('peak_enhancement','Peak concentration',1,7,.1),
            ('ripple_ratio','Small ripple / wave size',.05,.25,.01),('micro_detail','Small ripple strength',0,1,.05)]:number(*args,form)
        self.appearance_controls['ripple_ratio'].setToolTip('Changes the small-wave spectral band. Has no effect when Small ripple strength is zero; wavelengths below three blocks are limited to remain resolvable.')
        self.wave_hint=QLabel('Colour preview updates automatically. Bake commits blocks. Small-ripple size needs nonzero ripple strength.');self.wave_hint.setWordWrap(True);form.addRow(self.wave_hint)
        self.ocean_colours_box,self.ocean_colour_form=group('OCEAN COLOURS')
        for args in [('lit_strength','Lit colour strength',0,1,.05),('depth_colour_influence','Depth colour influence',0,1,.05),
            ('depth_colour_reach','Depth colour reach · blocks',1,2048,1),('shading_strength','Wave shading strength',0,1,.05),
            ('shading_contrast','Wave shading contrast',0,6,.1),('shading_midpoint','Wave shading midpoint',0,1,.01),
            ('shadow_softness','Shadow softness · blocks',0,12,.5)]:number(*args,self.ocean_colour_form)
        hints={'lit_strength':'0 removes lit colour. 1 allows fully lit faces to use the lit colour.',
            'depth_colour_influence':'0 removes depth from colour mixing only. 1 doubles the lit contribution at zero depth, capped at 100%.',
            'depth_colour_reach':'The extra shallow-water tint fades smoothly to zero at this actual depth.',
            'shading_strength':'0 applies lit tint evenly; 1 follows the full wave-face illumination.',
            'shadow_softness':'Softens water-body shading in world blocks. Does not blur foam, reflections or normals.'}
        for key,hint in hints.items():self.appearance_controls[key].setToolTip(hint)
        self.colour_effect_info=QLabel();self.colour_effect_info.setWordWrap(True);self.ocean_colour_form.addRow(self.colour_effect_info)
        self.ocean_depth_box,self.ocean_depth_form=group('OCEAN DEPTH')
        number('shallow_depth','Shallowest depth · blocks',0,2048,1,self.ocean_depth_form)
        depth_mode=QComboBox();depth_mode.addItem('Physical slope','slope');depth_mode.addItem('Depth rise across selection','span')
        depth_mode.currentIndexChanged.connect(self.changed);self.appearance_controls['depth_mode']=depth_mode
        self.ocean_depth_form.addRow(depth_mode)
        number('depth_refraction','Depth refraction · experimental',0,1,.1,self.ocean_depth_form)
        number('depth_rise','Depth rise · blocks',0,2048,1,self.ocean_depth_form)
        self.depth_info=QLabel();self.depth_info.setWordWrap(True);self.ocean_depth_form.addRow(self.depth_info)
        self.water_lighting_box,form=group('REFLECTIONS / LIGHTING')
        color('crest','Reflection colour',form)
        for args in [('reflection','Reflection strength',0,1,.05),('roughness','Reflection softness',0,1,.05),
            ('view_direction','Reflection view direction · degrees',0,360,5),('view_elevation','Reflection view elevation · degrees',10,90,5),
            ('light_direction','Light direction · degrees',0,360,5),('light_elevation','Light elevation · degrees',10,85,5)]:number(*args,form)
        for key,hint in {
            'reflection':'Brightness of eligible highlights. Their coverage depends on normals, light and bake view; strength alone cannot light every face.',
            'roughness':'Broadens the reflection highlight around the light/view alignment. Preview changes in the Colour preview tab.',
            'view_direction':'Virtual viewing bearing for fixed reflection highlights: 0° east (+X), 90° south (+Z), 180° west, 270° north. Orbiting the preview does not change it.',
            'view_elevation':'Virtual viewing angle above the water: low angles look across it; 90° looks straight down. Changes highlights, not wave geometry.'
        }.items():self.appearance_controls[key].setToolTip(hint)
        self.foam_box,form=group('FOAM')
        style=QComboBox();style.addItem('Lua-style crests','lua_crests');style.addItem('Lua whitecaps','whitecaps');style.addItem('Legacy foam','classic')
        self.appearance_controls['foam_style']=style;form.addRow('Foam treatment',style)
        style.row_widget=style;style.row_label=form.labelForField(style)
        style.setToolTip('Changes foam appearance only, inside existing eligible areas. Lua whitecaps use crest compression and the downwind front slope; FFT, procedural, Lua wave and map modes. Updates the live target; Bake applies it to blocks.')
        style.label_help=LabelHelp(style,style.row_label)
        style.currentIndexChanged.connect(self.changed)
        color('foam_colour','Foam colour',form)
        for args in [('foam','Foam amount',0,1,.05),('crest_bias','Foundation crest foam bias',0,.3,.01)]:number(*args,form)
        self.lava_box,form=group('LAVA COLOURS / HEAT')
        heatmode=QComboBox();heatmode.addItem('Valley / fissure interpretation','valleys');heatmode.addItem('Slope interpretation','slope')
        heatmode.currentIndexChanged.connect(self.changed);self.appearance_controls['lava_heat_mode']=heatmode;form.addRow('Heat pattern',heatmode)
        for key,label in [('lava_cold','Cooled crust'),('lava_hot','Molten lava'),('lava_peak','Hottest lava')]:color(key,label,form)
        for args in [('lava_crust','Crust coverage',0,1,.05),('lava_glow','Baked glow strength',0,1,.05)]:number(*args,form)
        hint=QLabel('Glow is baked colour. Normal patches overlap without mirrored edge wrapping.');hint.setWordWrap(True);form.addRow(hint)
        _,form=group('BAKE OPTIONS')
        number('glass_layers','Stained glass layers',0,3,1,form)
        checkbox('gpu','Hardware acceleration',form)
        hint=QLabel('Edit settings, then Bake. Glass follows the solid pattern automatically.');hint.setWordWrap(True);form.addRow(hint)
        self.refresh_appearance_buttons();self.refresh_mode_visibility()

    def show_source_normal(self):
        self.thumbnail_baked=False
        if not hasattr(self,'normal_thumbnail'):return
        a=self.appearance_settings()
        if a['normal_source']=='imported':
            path=a['normal_map_path']
            try:
                image=normal_maps.read_image(path)
                self.set_normal_thumbnail(np.asarray(image,dtype=np.uint8))
                self.normal_caption.setText('Imported source normal map · before bake')
                self.source_preview_key=('imported',path)
            except (OSError,ValueError):
                self.normal_thumbnail.image=None;self.normal_thumbnail.update()
                self.normal_caption.setText('Import a normal map to preview it')
        elif self.active_mode=='lava':
            n,_=appearance.lava_surface.baseline(a['lava_pattern'])
            self.set_normal_thumbnail(np.clip((n*.5+.5)*255,0,255).astype(np.uint8))
            self.normal_caption.setText('Selected lava normal map · before bake')
            self.source_preview_key=('lava',a['lava_pattern'])
        elif a['surface_model']=='ocean_maps':
            n,_=appearance.ocean_library.baseline(a['ocean_pattern'])
            self.set_normal_thumbnail(np.clip((n*.5+.5)*255,0,255).astype(np.uint8))
            self.normal_caption.setText('Selected ocean normal map · before bake')
            self.source_preview_key=('ocean_maps',a['ocean_pattern'])
        else:
            self.source_preview_key=('ocean',a['surface_model'])
            if self.result and self.result.get('appearance_settings',{}).get('surface_model')==a['surface_model'] and self.result.get('appearance_settings',{}).get('normal_source')!='imported' and 'normal_rgb' in self.result:
                self.set_normal_thumbnail(self.result['normal_rgb'])
                self.normal_caption.setText('Last generated ocean normals · settings changed')
            else:
                self.normal_thumbnail.image=None;self.normal_thumbnail.update()
                self.normal_caption.setText('Ocean normals · Bake to generate')

    def import_normal_map(self):
        name,_=QFileDialog.getOpenFileName(self,'Import RGB normal map','','Normal maps (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)')
        if not name:return
        try:
            root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
            path=normal_maps.import_image(name,root/'normal_maps')
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Normal map import',str(exc));return
        source=self.appearance_controls['normal_source']
        source.setCurrentIndex(source.findData('imported'))
        self.appearance_values.update(normal_map_path=path,normal_map_name=Path(name).name)
        self.changed();self.show_source_normal()

    def setup_bake_panel(self):
        self.bake_panel=BakePanel(self.tabs,self.cancel_bake)
        self.bake_clock=QTimer(self);self.bake_clock.setInterval(500);self.bake_clock.timeout.connect(self.update_bake_progress)

    def make_bake_sidebar(self):
        panel=QWidget();panel.setMinimumWidth(200);panel.setMaximumWidth(300)
        layout=QVBoxLayout(panel);layout.setContentsMargins(10,8,10,8)
        layout.addWidget(QLabel('BAKE STATUS'))
        layout.addWidget(self.bake_state)
        self.normal_caption=QLabel('Normals · no bake yet');self.normal_caption.setWordWrap(True)
        layout.addWidget(self.normal_caption)
        self.normal_thumbnail=DraftCanvas();self.normal_thumbnail.setMinimumHeight(190)
        self.normal_thumbnail.setMaximumHeight(240);self.normal_thumbnail.draft=True
        layout.addWidget(self.normal_thumbnail)
        self.bake_details=QLabel('Surface normals drive both solid colour and glass.');self.bake_details.setWordWrap(True);self.bake_details.setMinimumHeight(110)
        layout.addWidget(self.bake_details)
        layout.addWidget(QLabel('LAST FIVE BAKED SETTINGS'))
        self.history_list=QListWidget();self.history_list.setMaximumHeight(140);layout.addWidget(self.history_list)
        self.history_restore=QPushButton('Restore selected settings');self.history_restore.clicked.connect(self.restore_bake_history)
        layout.addWidget(self.history_restore)
        note=QLabel('Restore a previous setting, then Bake. Your last five bakes are saved automatically.')
        note.setWordWrap(True);note.setObjectName('muted');layout.addWidget(note)
        layout.addStretch();layout.addWidget(self.bake_button)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(210);scroll.setMaximumWidth(320);scroll.setWidget(panel)
        return scroll

    def refresh_bake_sidebar(self,result):
        if 'normal_rgb' not in result:
            self.show_source_normal();return
        self.set_normal_thumbnail(result['normal_rgb'])
        self.normal_caption.setText('Current baked surface normals')
        used=sum(n>0 for n in result['surface_counts'])
        self.bake_details.setText(f'{result["settings"]["width"]} × {result["settings"]["length"]} blocks\n'
            f'{used} solid materials · {result["stats"]["glass_blocks"]:,} glass blocks\n'
            'Glass shares the surface pattern. Baked lighting stays fixed while orbiting.')

    def set_normal_thumbnail(self,pixels):
        pixels=np.ascontiguousarray(pixels,dtype=np.uint8);h,w=pixels.shape[:2]
        self.normal_thumbnail.image=QImage(pixels.data,w,h,w*3,QImage.Format.Format_RGB888).copy()
        self.normal_thumbnail.update()

    def load_bake_history(self,entries):
        self.bake_history=[]
        if not isinstance(entries,list):return
        for entry in entries[:5]:
            try:
                c=colour.validate(entry['colour'])
                self.bake_history.append(dict(settings=ocean.validate(entry['settings']),colour=c,
                    appearance=appearance.validate(appearance.water_depth.migrate(entry['appearance'],colour.validate(entry['colour']),entry['settings'])),label=str(entry.get('label','Saved bake'))))
            except (KeyError,ValueError,TypeError):continue
        self.refresh_history_list()

    def refresh_history_list(self):
        self.history_list.clear()
        for entry in self.bake_history:self.history_list.addItem(entry['label'])
        if self.bake_history:self.history_list.setCurrentRow(0)

    def remember_bake(self,result):
        entry=copy.deepcopy(dict(settings=result['settings'],colour=result['colour_settings'],appearance=result['appearance_settings']))
        self.bake_history=[e for e in self.bake_history if any(e[k]!=entry[k] for k in entry)]
        mode='Lava' if entry['appearance']['surface_model']=='lava' else 'Ocean'
        entry['label']=datetime.now().strftime('%H:%M:%S')+f' · {mode} · {entry["settings"]["width"]}×{entry["settings"]["length"]}'
        self.bake_history.insert(0,entry);self.bake_history=self.bake_history[:5];self.refresh_history_list()

    def restore_bake_history(self):
        index=self.history_list.currentRow()
        if index<0 or self.baking or self.generating or self.exporting:return
        entry=copy.deepcopy(self.bake_history[index])
        self.capture_material_mode()
        self.active_mode='lava' if entry['appearance']['surface_model']=='lava' else 'ocean'
        self.apply_material_settings(entry)
        self.apply_control_values(self.controls,entry['settings'])
        self.changed()
        self.bake_state.setText('History settings restored · Press Bake to apply.')

    def generation_is_generated(self):
        source=self.appearance_controls['normal_source'].currentData()
        model=self.appearance_controls['surface_model'].currentData()
        return self.active_mode!='lava' and source!='imported' and model in ('fft_normals','procedural','lua_waves')

    def appearance_settings(self):
        values={**self.appearance_values,**{k:w.isChecked() if isinstance(w,QCheckBox) else w.currentData() if isinstance(w,QComboBox) else w.value()
            for k,w in self.appearance_controls.items()}}
        if not self.generation_is_generated():
            # Imported maps and Lava keep one shared foundation/map heading.
            values['link_direction']=True
        if values['link_direction']:
            values['wind_direction']=self.controls['direction'].value()
        if self.generation_is_generated() and values['link_scale']:
            values['ripple_scale']=min(256,max(4,self.controls['wavelength'].value()*values['scale_ratio']))
        if self.active_mode=='lava':values['surface_model']='lava'
        return appearance.validate(values)

    def generation_key(self):
        source=self.appearance_controls['normal_source'].currentData()
        model=self.appearance_controls['surface_model'].currentData()
        return self.active_mode+':'+('imported' if source=='imported' else 'built_in' if self.active_mode=='lava' else model)

    def select_surface_source(self):
        selected=self.surface_source.currentData()
        if selected is None:return
        source=self.appearance_controls['normal_source'];model=self.appearance_controls['surface_model']
        source.blockSignals(True);model.blockSignals(True)
        source.setCurrentIndex(source.findData('imported' if selected=='imported' else 'built_in'))
        if selected not in ('imported','built_in'):model.setCurrentIndex(model.findData(selected))
        source.blockSignals(False);model.blockSignals(False)
        self.switch_generation()

    def sync_surface_source(self):
        options=[('Supplied lava maps','built_in'),('Imported normal map','imported')] if self.active_mode=='lava' else [
            ('FFT ocean normals','fft_normals'),('Procedural wave groups','procedural'),('Lua wave model','lua_waves'),('Ocean normal library','ocean_maps'),('Imported normal map','imported')]
        selected=self.generation_key().split(':',1)[1]
        self.surface_source.blockSignals(True)
        if [self.surface_source.itemData(i) for i in range(self.surface_source.count())]!=[key for _,key in options]:
            self.surface_source.clear()
            for label,key in options:self.surface_source.addItem(label,key)
        self.surface_source.setCurrentIndex(self.surface_source.findData(selected));self.surface_source.blockSignals(False)

    def capture_generation(self):
        values=self.appearance_settings()
        self.generation_profiles[self.active_generation]=copy.deepcopy({k:values[k] for k in self.GENERATION_KEYS})
        return self.generation_profiles

    def switch_generation(self):
        selected=self.generation_key()
        if selected!=self.active_generation:
            self.capture_generation()
            values=appearance.validate(self.generation_profiles.get(selected,{}))
            values={k:values[k] for k in self.GENERATION_KEYS}
            self.appearance_values.update(values)
            self.apply_control_values(self.appearance_controls,values)
            self.active_generation=selected
        self.changed()

    def load_generation_profiles(self,profiles):
        self.generation_profiles={}
        if not isinstance(profiles,dict):return
        for key,entry in profiles.items():
            if key not in ('ocean:fft_normals','ocean:procedural','ocean:lua_waves','ocean:ocean_maps','ocean:imported','lava:built_in','lava:imported'):continue
            values=appearance.validate(entry)
            self.generation_profiles[key]={k:values[k] for k in self.GENERATION_KEYS}

    def capture_material_mode(self):
        self.capture_generation()
        self.mode_settings[self.active_mode]=copy.deepcopy(dict(colour=self.colour_settings(),appearance=self.appearance_settings()))
        return self.mode_settings

    def refresh_mode_visibility(self):
        # Each normal source shows only the controls it consumes plus shared
        # colour/lighting/bake controls. Numeric rows hide their labels too.
        if 'surface_model' not in getattr(self,'appearance_controls',{}):return
        from PySide6.QtWidgets import QFormLayout
        source=self.appearance_controls['normal_source'].currentData()
        model=self.appearance_controls['surface_model'].currentData()
        base={'normal_strength','seed','invert_normals','glass_layers','gpu','wave_spacing'}
        colour={'lit_strength','depth_colour_influence','depth_colour_reach','shading_strength','shading_contrast','shading_midpoint','shadow_softness'}
        light={'reflection','roughness','view_direction','view_elevation','light_direction','light_elevation'}
        foam={'foam','crest_bias'}
        ocean=base|colour|light|foam
        gen={'ripple_scale','link_scale','scale_ratio','link_direction','wind_direction','breakup','micro_detail'}
        depth={'depth_mode','depth_refraction','depth_rise'}
        fft=ocean|gen|depth|{'wind','choppiness','peak_enhancement','ripple_ratio','swell_strength','swell_scale','foundation_normals','foam_style'}
        procedural=ocean|gen|depth|{'wind','swell_strength','swell_scale','foundation_normals','foam_style'}
        lua=ocean|gen|{'wind','foam_style','lua_layers'}
        maps=ocean|{'wind','imported_span','normal_rotation','imported_flip_y','ocean_pattern'}
        lava={'normal_strength','seed','invert_normals','glass_layers','gpu','lava_pattern','lava_scale','lava_distortion','lava_flip_y','lava_sampling','lava_heat_mode','lava_crust','lava_glow'}
        if self.active_mode=='lava':allowed=lava
        elif source=='imported' or model=='ocean_maps':allowed=maps
        elif model=='fft_normals':allowed=fft
        elif model=='procedural':allowed=procedural
        else:allowed=lua
        linked_scale=self.appearance_controls['link_scale'].isChecked()
        linked_direction=self.appearance_controls['link_direction'].isChecked()
        signature=(self.active_mode,source,model,linked_scale,linked_direction,
                   self.appearance_controls['depth_mode'].currentData())
        if getattr(self,'_visibility_signature',None)==signature:return
        self._visibility_signature=signature
        for key,widget in self.appearance_controls.items():
            visible=key in allowed
            if key=='wind_direction':visible=visible and not linked_direction
            if key=='scale_ratio':visible=visible and linked_scale
            if key=='depth_rise':visible=visible and self.appearance_controls['depth_mode'].currentData()=='span'
            if hasattr(widget,'row_widget'):
                widget.row_widget.setVisible(visible);widget.row_label.setVisible(visible)
            else:
                widget.setVisible(visible)
                parent=widget.parentWidget();layout=parent.layout() if parent is not None else None
                if isinstance(layout,QFormLayout):
                    label=layout.labelForField(widget)
                    if label is not None:label.setVisible(visible)

    def apply_control_values(self,controls,values):
        for key,w in controls.items():
            if key not in values:continue
            w.blockSignals(True)
            if isinstance(w,QCheckBox):w.setChecked(values[key])
            elif isinstance(w,QComboBox):w.setCurrentIndex(max(0,w.findData(values[key])))
            else:
                w.setValue(values[key])
                if hasattr(w,'slider'):w.slider.setValue(round(w.value()*(10**w.decimals() if isinstance(w,QDoubleSpinBox) else 1)))
            w.blockSignals(False)

    def apply_material_settings(self,entry):
        self.colour_values=colour.validate(entry['colour'])
        self.appearance_values=appearance.validate(appearance.water_depth.migrate(entry['appearance'],self.colour_values,entry.get('settings',self.settings())))
        if self.active_mode=='lava':self.appearance_values['surface_model']='lava'
        self.apply_control_values(self.colour_controls,self.colour_values)
        self.apply_control_values(self.appearance_controls,self.appearance_values)
        self.material_mode.blockSignals(True)
        self.material_mode.setCurrentIndex(self.material_mode.findData(self.active_mode))
        self.material_mode.blockSignals(False)
        self.active_generation=self.generation_key()
        self.capture_generation()
        self.refresh_colour_buttons();self.refresh_appearance_buttons()

    def switch_material_mode(self):
        selected=self.material_mode.currentData()
        if selected==self.active_mode:return
        self.capture_material_mode();self.active_mode=selected
        default=dict(colour=colour.validate({}),
                     appearance=appearance.validate(dict(surface_model='lava' if selected=='lava' else 'fft_normals')))
        self.apply_material_settings(copy.deepcopy(self.mode_settings.get(selected,default)))
        self.changed()

    def refresh_appearance_buttons(self):
        for key,button in self.appearance_buttons.items():
            value=self.appearance_values[key];colour_value=QColor(value)
            text='#10202a' if colour_value.lightnessF()>.55 else '#ffffff'
            button.setText(value.upper());button.setStyleSheet(f'background:{value};color:{text};padding:9px;')

    def pick_appearance_colour(self,key):
        value=QColorDialog.getColor(QColor(self.appearance_values[key]),self,'Choose '+key.replace('_',' '))
        if value.isValid():
            self.appearance_values[key]=value.name();self.refresh_appearance_buttons();self.changed()

    def start_bake(self):
        if self.baking or self.generating or self.exporting: return
        self.stop_colour_preview()
        try:
            s=ocean.validate(self.settings());c=colour.validate(self.colour_settings());a=self.appearance_settings()
            if not c['enabled']: return
        except ValueError as exc: self.status.setText(str(exc));return
        self.bake_button.setEnabled(False);self.history_restore.setEnabled(False)
        self.timer.stop();self.baking=True;self.bake_cancel=threading.Event();self.bake_latest=None;self.bake_started=time.perf_counter()
        self.control_tabs.setEnabled(False);self.export_button.setEnabled(False);self.png_button.setEnabled(False)
        self.preview.setEnabled(False);self.heightmap.setEnabled(False)
        self.bake_panel.canvas.image=self.preview.grab().toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        self.bake_panel.canvas.draft=False;self.bake_panel.stage.setText('Starting bake… Previous result is dimmed.')
        self.bake_panel.cancel.setEnabled(True);self.bake_panel.bar.setRange(0,0)
        self.bake_panel.setGeometry(self.tabs.rect());self.bake_panel.show();self.bake_panel.raise_()
        self.bake_clock.start();self.bake_state.setText('Baking…');self.status.setText('Baking procedural surface…')
        if a['gpu'] and QApplication.platformName() not in ('offscreen','minimal'):
            fmt=QSurfaceFormat();fmt.setVersion(3,0);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
            self.bake_surface=QOffscreenSurface();self.bake_surface.setFormat(fmt);self.bake_surface.create()
        surface=self.bake_surface
        def progress(data):
            with self.bake_lock:
                if data['image'] is None and self.bake_latest is not None: data['image']=self.bake_latest['image']
                if data.get('normal') is None and self.bake_latest is not None:data['normal']=self.bake_latest.get('normal')
                self.bake_latest=data
        self.run_job(self.revision,lambda:baker.bake(s,c,a,progress,self.bake_cancel,surface),self.baked)

    def update_bake_progress(self):
        if not self.baking: return
        self.bake_panel.elapsed.setText(f'{time.perf_counter()-self.bake_started:.1f} seconds elapsed · Draft refresh every 0.5 seconds')
        with self.bake_lock: data=self.bake_latest
        if data is None: return
        self.bake_state.setText(data['stage']+f' · {time.perf_counter()-self.bake_started:.1f}s')
        if data.get('normal') is not None:
            self.set_normal_thumbnail(data['normal']);self.normal_caption.setText('Baking · current normal draft')
        self.bake_panel.stage.setText(data['stage'])
        if data['total']:
            self.bake_panel.bar.setRange(0,data['total']);self.bake_panel.bar.setValue(data['done'])
            self.bake_panel.bar.setFormat(f'{data["done"]:,} / {data["total"]:,}')
        else: self.bake_panel.bar.setRange(0,0)
        if data['image'] is not None:
            pixels=np.ascontiguousarray(data['image'],dtype=np.uint8);h,w=pixels.shape[:2]
            self.bake_panel.canvas.image=QImage(pixels.data,w,h,w*3,QImage.Format.Format_RGB888).copy()
            self.bake_panel.canvas.draft=True;self.bake_panel.canvas.update()

    def cancel_bake(self):
        if self.bake_cancel is not None:
            self.bake_cancel.set();self.bake_panel.cancel.setEnabled(False);self.bake_panel.stage.setText('Cancelling at the next work checkpoint…')

    def baked(self,token,result,error):
        cancelled=self.bake_cancel.is_set()
        self.baking=False;self.bake_clock.stop();self.bake_panel.hide()
        self.control_tabs.setEnabled(True);self.preview.setEnabled(True);self.heightmap.setEnabled(True)
        if self.bake_surface is not None: self.bake_surface.destroy();self.bake_surface=None
        if cancelled or error or token!=self.revision:
            message='Bake cancelled · Previous result retained.' if cancelled else 'Bake failed: '+error if error else 'Bake discarded: settings changed.'
            self.status.setText(message);self.bake_state.setText(message+' Bake required.')
            self.history_restore.setEnabled(True)
            self.export_button.setEnabled(self.result_current());self.bake_button.setEnabled(True)
            self.png_button.setEnabled(self.result is not None and self.result['settings']==self.settings())
            return
        self.generated(token,result,'')
        self.preview_stale.hide()
        self.set_colour_preview(result)
        self.remember_bake(result)
        if hasattr(self,'autosave_timer'):self.autosave_timer.start()
        self.history_restore.setEnabled(True)
        inversion=' · Inverted' if result['appearance_settings']['invert_normals'] else ''
        self.thumbnail_baked=True
        self.normal_caption.setText('Current baked surface normals'+inversion)
        self.bake_state.setText(f'Baked{inversion} · {result["bake_seconds"]:.2f}s')
        self.status.setText(f'Bake complete · {result["stats"]["blocks"]:,} blocks · {result["stats"]["glass_blocks"]:,} glass blocks · Ready')
