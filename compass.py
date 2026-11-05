"""Camera-projected Minecraft north indicator shared by both viewports."""
import math
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


def north_vector(yaw, pitch, top=False):
    if top:
        return 0., -1.
    return math.sin(yaw), -math.cos(yaw) * math.sin(pitch)


class Compass(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip('North · Minecraft −Z')
        self.resize(88, 88)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#526978'), 1))
        p.setBrush(QColor(16, 29, 41, 210));p.drawEllipse(5, 5, 77, 77)
        dx, dy = north_vector(self.owner.yaw, self.owner.pitch, self.owner.top)
        length = max(.01, math.hypot(dx, dy));dx /= length;dy /= length
        centre = QPointF(44, 44);tip = centre + QPointF(dx*23, dy*23)
        p.setPen(QPen(QColor('#91f2df'), 2.5));p.drawLine(centre, tip)
        for sign in (-1, 1):
            p.drawLine(tip, tip + QPointF(-dx*9-sign*dy*5, -dy*9+sign*dx*5))
        p.setPen(QColor('#ffffff'))
        p.drawText(int(40+dx*32), int(49+dy*32), 'N')
