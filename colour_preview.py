"""Debounced sampled appearance preview; full blocks remain committed by Bake."""
import threading
import numpy as np
from PySide6.QtCore import Qt,QTimer,QRectF
from PySide6.QtGui import QPainter,QColor,QImage
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel
import quick_colour


class ColourCanvas(QWidget):
    def __init__(self):
        super().__init__();self.image=None;self.setMinimumSize(160,160)
    def set_pixels(self,rgb):
        pixels=np.ascontiguousarray(rgb,dtype=np.uint8);h,w=pixels.shape[:2]
        self.image=QImage(pixels.data,w,h,w*3,QImage.Format.Format_RGB888).copy();self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#10202a'))
        if self.image is not None:
            size=self.image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            p.drawImage(QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height()),self.image)
        p.end()


class ColourPreviewMixin:
    def setup_colour_preview(self):
        page=QWidget();layout=QVBoxLayout(page);row=QHBoxLayout()
        for title,attribute in [('Target appearance · live preview','target_canvas'),('Minecraft approximation · last bake','matched_canvas')]:
            column=QVBoxLayout();caption=QLabel(title);caption.setWordWrap(True)
            column.addWidget(caption);canvas=ColourCanvas();setattr(self,attribute,canvas)
            column.addWidget(canvas,1);row.addLayout(column,1)
        layout.addLayout(row,1)
        self.colour_preview_status=QLabel('Preparing live appearance preview…');self.colour_preview_status.setWordWrap(True)
        layout.addWidget(self.colour_preview_status)
        self.match_quality=QLabel();self.match_quality.setWordWrap(True);layout.addWidget(self.match_quality)
        self.tabs.addTab(page,'Colour preview')
        self.colour_preview_timer=QTimer(self);self.colour_preview_timer.setSingleShot(True)
        self.colour_preview_timer.timeout.connect(self.update_colour_preview)
        self.colour_preview_busy=False;self.colour_preview_pending=False
        self.last_colour_result=None
        self.colour_preview_cache=None;self.colour_preview_cancel=None

    def set_colour_preview(self,result):
        if 'preview_fields' not in result:return
        old=self.last_colour_result
        self.last_colour_result={key:result[key] for key in ('settings','colour_settings','appearance_settings',
            'preview_fields','preview_footprint','target_rgb','solid_rgb','glass_stacks')}
        self.colour_preview_cache=quick_colour.from_bake(result)
        self.matched_canvas.set_pixels(result['block_rgb'])
        self.target_canvas.set_pixels(result['target_rgb'])
        error=result['mean_colour_error'];grade='Close' if error<5 else 'Approximate' if error<12 else 'Limited palette match'
        message=f'{grade} · Mean colour difference: {error:.1f} Lab units (lower is closer). Glass is an approximation.'
        if old and old['target_rgb'].shape==result['target_rgb'].shape:
            if not np.array_equal(old['target_rgb'],result['target_rgb']) and np.array_equal(old['solid_rgb'],result['solid_rgb']) and np.array_equal(old['glass_stacks'],result['glass_stacks']):
                message+=' Target changed; the same blocks remain the closest match.'
        self.match_quality.setText(message)
        self.last_match_message=message
        self.colour_preview_status.setText('Target and Minecraft approximation are from the current bake.')

    def schedule_colour_preview(self):
        if not hasattr(self,'colour_preview_timer'):return
        if self.colour_preview_cancel is not None:self.colour_preview_cancel.set()
        self.colour_preview_pending=True
        self.colour_preview_timer.start(180)

    def stop_colour_preview(self):
        self.colour_preview_timer.stop();self.colour_preview_pending=False
        if self.colour_preview_cancel is not None:self.colour_preview_cancel.set()

    def update_colour_preview(self):
        if self.baking:return
        if self.generating or self.timer.isActive():
            self.colour_preview_timer.start(60);return
        a=self.appearance_settings();c=self.colour_settings();s=self.settings()
        if not c['enabled']:
            self.colour_preview_pending=False
            self.colour_preview_status.setText('Colour layer disabled. Enable it to preview appearance.')
            return
        if self.colour_preview_busy:
            self.colour_preview_pending=True;return
        self.colour_preview_busy=True;self.colour_preview_pending=False
        cancel=threading.Event();self.colour_preview_cancel=cancel
        cached=self.colour_preview_cache
        previous=self.result
        # Workers read snapshots; only the current revision may publish its cache/image.
        def check():
            if cancel.is_set():raise RuntimeError('Superseded preview')
        def compute():
            return quick_colour.render(s,c,a,cached,previous,check)
        def finished(token,data,error):
            self.colour_preview_busy=False
            if token==self.revision and not self.baking and not cancel.is_set():
                if error:self.colour_preview_status.setText('Quick preview unavailable. Bake to update.')
                else:
                    self.colour_preview_cache=data['cache']
                    self.target_canvas.set_pixels(data['rgb'])
                    self.colour_preview_status.setText('Live target · colours, reflections and foam update automatically. Blending and blocks update with Bake.')
                    if self.last_colour_result is None:self.match_quality.setText('No full bake yet. The right image will show the last baked Minecraft approximation.')
                    else:self.match_quality.setText('Last full bake: '+self.last_match_message)
            if self.colour_preview_pending and not self.baking:self.colour_preview_timer.start(0)
        self.run_job(self.revision,compute,finished)
