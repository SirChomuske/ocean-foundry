"""Synchronized sliders and editable numeric controls."""
import secrets
from PySide6.QtCore import Qt,QObject,QEvent,QPoint,QRect
from PySide6.QtWidgets import QWidget,QHBoxLayout,QSlider,QDoubleSpinBox,QPushButton,QLabel,QAbstractScrollArea,QAbstractSpinBox


class LabelHelp(QObject):
    """Label-only help outside the control panel, without intercepting input."""
    def __init__(self,spin,label):
        super().__init__(spin);self.spin=spin;self.label=label;self.showing=False
        self.popup=QLabel(label,Qt.WindowType.ToolTip|Qt.WindowType.WindowTransparentForInput|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.popup.setWordWrap(True);self.popup.setMargin(10)
        self.popup.setStyleSheet('QLabel { background: #fff8d8; color: #18212b; border: 1px solid #8b846e; border-radius: 4px; }')
        spin.installEventFilter(self);label.installEventFilter(self)
        if hasattr(spin,'slider'):spin.slider.installEventFilter(self)
        self.sync()
    def sync(self):
        self.label.setToolTip(self.spin.toolTip())
    def show(self,pos):
        panel=self.spin.row_widget
        ancestor=self.label.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor,QAbstractScrollArea):panel=ancestor;break
            ancestor=ancestor.parentWidget()
        rect=QRect(panel.mapToGlobal(QPoint()),panel.size())
        screen=self.label.screen().availableGeometry()
        spaces=((rect.right()+13,screen.right()-rect.right()-24),
                (screen.left()+12,rect.left()-screen.left()-24))
        self.popup.setText(self.label.toolTip())
        for left,room in spaces:
            if room<180:continue
            width=min(340,room);self.popup.setFixedWidth(width);self.popup.adjustSize()
            if left<rect.left():left=rect.left()-12-width
            top=max(screen.top()+6,min(pos.y()+16,screen.bottom()-self.popup.height()-6))
            bounds=QRect(QPoint(left,top),self.popup.size())
            # Includes every slider/number box, even if forms have no scroll panel.
            controls=self.label.window().findChildren(QSlider)+self.label.window().findChildren(QAbstractSpinBox)
            if any(w.isVisible() and bounds.intersects(QRect(w.mapToGlobal(QPoint()),w.size())) for w in controls):continue
            self.popup.move(left,top);self.popup.show();self.showing=True;return
    def eventFilter(self,obj,event):
        if obj is self.spin and event.type()==QEvent.Type.ToolTipChange:self.sync()
        if obj is self.label:
            if event.type()==QEvent.Type.ToolTip and self.label.toolTip():
                self.show(event.globalPos());return True
            if event.type() in (QEvent.Type.Leave,QEvent.Type.Hide) and self.showing:
                self.popup.hide();self.showing=False
        elif event.type()==QEvent.Type.ToolTip:
            return True
        return False

class EnabledLink(QObject):
    def __init__(self,spin,slider):
        super().__init__(spin);self.spin=spin;self.slider=slider;spin.installEventFilter(self)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.EnabledChange:self.slider.setEnabled(self.spin.isEnabled())
        return False

def numeric_row(form,label,spin,help_text=''):
    if help_text:spin.setToolTip(help_text)
    # Seeds are identifiers, not quantities with a meaningful slider scale.
    if spin.maximum()>100000:
        row=QWidget();line=QHBoxLayout(row);line.setContentsMargins(0,0,0,0)
        randomize=QPushButton('Random');randomize.setToolTip('Choose a new random seed')
        def choose():
            previous=spin.value();value=secrets.randbelow(int(spin.maximum())+1)
            if value==previous:value=(value+1)%(int(spin.maximum())+1)
            spin.setValue(value)
        randomize.clicked.connect(choose)
        line.addWidget(spin,1);line.addWidget(randomize);form.addRow(label,row)
        spin.random_button=randomize;spin.enabled_link=EnabledLink(spin,randomize)
        spin.row_widget=row;spin.row_label=form.labelForField(row)
        spin.label_help=LabelHelp(spin,spin.row_label);return
    row=QWidget();line=QHBoxLayout(row);line.setContentsMargins(0,0,0,0)
    slider=QSlider(Qt.Orientation.Horizontal)
    factor=10**spin.decimals() if isinstance(spin,QDoubleSpinBox) else 1
    slider.setRange(round(spin.minimum()*factor),round(spin.maximum()*factor))
    slider.setValue(round(spin.value()*factor));slider.setSingleStep(max(1,round(spin.singleStep()*factor)))
    slider.setMinimumWidth(90);spin.setMinimumWidth(72);spin.setMaximumWidth(100)
    slider.valueChanged.connect(lambda value:spin.setValue(value/factor if factor>1 else value))
    def sync(value):
        slider.blockSignals(True);slider.setValue(round(value*factor));slider.blockSignals(False)
    spin.valueChanged.connect(sync);spin.slider=slider;spin.enabled_link=EnabledLink(spin,slider)
    line.addWidget(slider,1);line.addWidget(spin);form.addRow(label,row)
    spin.row_widget=row;spin.row_label=form.labelForField(row)
    spin.label_help=LabelHelp(spin,spin.row_label)
