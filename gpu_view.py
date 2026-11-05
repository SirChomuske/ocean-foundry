"""Native OpenGL viewport: persistent mesh buffer, one draw call per frame."""
import math
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QSurfaceFormat, QVector4D, QImage
import numpy as np
from PySide6.QtWidgets import QLabel
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject, QOpenGLTexture

VERTEX = '''#version 130
in vec3 position;
in vec3 colour;
uniform vec4 camera;
uniform vec4 projection;
uniform vec4 textureSettings;
out vec3 faceColour;
out vec2 surfaceUV;
void main() {
    float rx=position.x*camera.x-position.z*camera.y;
    float rz=position.x*camera.y+position.z*camera.x;
    float screenY=position.y*camera.z-rz*camera.w;
    float depth=rz*camera.z+position.y*camera.w;
    gl_Position=vec4(rx*projection.x,screenY*projection.y-0.14,-depth*projection.z,1.0);
    faceColour=colour;
    surfaceUV=vec2(position.x/textureSettings.x+.5,position.z/textureSettings.y+.5);
}
'''
FRAGMENT = '''#version 130
in vec3 faceColour;
in vec2 surfaceUV;
uniform sampler2D surfaceTexture;
uniform vec4 textureSettings;
out vec4 fragmentColour;
void main() { fragmentColour=vec4(faceColour*(textureSettings.z>.5?texture(surfaceTexture,surfaceUV).rgb:vec3(1)),1.0); }
'''


class GPUView(QOpenGLWidget):
    failed=Signal(str)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner=owner
        fmt=QSurfaceFormat()
        fmt.setVersion(3,0)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.program=None; self.buffer=None; self.vao=None
        self.texture=None
        self.result=None; self.pending=True; self.ready=False
        self.renderer=''; self.error=''; self.upload_count=0; self.frame_count=0
        self.hint=QLabel('Drag to orbit · Scroll to zoom · Double-click to reset',self)
        self.caption=QLabel('Preparing preview…',self)
        for label in [self.hint,self.caption]:
            label.setStyleSheet('background: transparent; color: #b6ccd9;')
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def report_failure(self,error):
        self.error=str(error); self.ready=False
        QTimer.singleShot(0,lambda:self.failed.emit(self.error))

    def initializeGL(self):
        try:
            self.gl=self.context().functions()
            self.renderer=self.gl.glGetString(0x1F01)
            self.software_driver=any(name in self.renderer.lower() for name in ('llvmpipe','softpipe','software','gdi generic'))
            self.program=QOpenGLShaderProgram(self)
            self.program.bindAttributeLocation('position',0)
            self.program.bindAttributeLocation('colour',1)
            for kind,source in [(QOpenGLShader.ShaderTypeBit.Vertex,VERTEX),
                                (QOpenGLShader.ShaderTypeBit.Fragment,FRAGMENT)]:
                if not self.program.addShaderFromSourceCode(kind,source):
                    raise RuntimeError(self.program.log())
            if not self.program.link(): raise RuntimeError(self.program.log())
            self.camera_location=self.program.uniformLocation('camera')
            self.projection_location=self.program.uniformLocation('projection')
            self.vao=QOpenGLVertexArrayObject(self)
            self.buffer=QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not self.vao.create() or not self.buffer.create():
                raise RuntimeError('Could not create GPU mesh buffers.')
            self.buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.ready=True; self.pending=True
        except Exception as exc:
            self.report_failure(exc)

    def cleanup(self):
        self.makeCurrent()
        if self.buffer is not None: self.buffer.destroy()
        if self.vao is not None: self.vao.destroy()
        if self.texture is not None: self.texture.destroy();self.texture=None
        if self.program is not None: self.program.removeAllShaders()
        self.ready=False; self.pending=True
        self.doneCurrent()

    def set_result(self,result):
        self.result=result; self.pending=True
        self.update()

    def paintGL(self):
        if not self.ready: return
        try:
            gl=self.gl
            gl.glClearColor(16/255,29/255,41/255,1)
            gl.glClear(0x4000|0x0100) # Colour and depth.
            if self.result is None: return
            m=self.result['mesh']
            self.vao.bind(); self.buffer.bind(); self.program.bind()
            if self.pending:
                data=self.result['gpu_vertices']
                self.buffer.allocate(data,len(data))
                self.vertex_count=len(data)//24
                for index,offset in [(0,0),(1,12)]:
                    self.program.enableAttributeArray(index)
                    self.program.setAttributeBuffer(index,0x1406,offset,3,24)
                if gl.glGetError()!=0: raise RuntimeError('GPU mesh upload failed.')
                self.pending=False; self.upload_count+=1
                if self.texture is not None: self.texture.destroy();self.texture=None
                if 'preview_texture' in self.result:
                    pixels=np.ascontiguousarray(self.result['preview_texture'],dtype=np.uint8);h,w=pixels.shape[:2]
                    img=QImage(pixels.data,w,h,w*3,QImage.Format.Format_RGB888).copy()
                    self.texture=QOpenGLTexture(img,QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
                    self.texture.setMinMagFilters(QOpenGLTexture.Filter.Nearest,QOpenGLTexture.Filter.Nearest)
                    self.texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            gl.glEnable(0x0B71) # Depth test replaces CPU face sorting.
            gl.glDepthFunc(0x0201)
            gl.glDisable(0x0B44) # Draw both sides of the surface mesh.
            gl.glDisable(0x0BE2)
            scale=min((self.width()-80)/(m['width']+m['length']),
                (self.height()-110)/(max(m['width'],m['length'])+m['height']))*1.5*self.owner.zoom
            self.program.setUniformValue(self.camera_location,QVector4D(
                math.cos(self.owner.yaw),math.sin(self.owner.yaw),
                math.cos(self.owner.pitch),math.sin(self.owner.pitch)))
            self.program.setUniformValue(self.projection_location,QVector4D(
                2*scale/max(1,self.width()),2*scale/max(1,self.height()),
                1/(m['width']+m['length']+m['height']),0))
            self.program.setUniformValue(self.program.uniformLocation('textureSettings'),QVector4D(m['width'],m['length'],1 if self.texture else 0,0))
            if self.texture is not None:
                self.texture.bind(0);gl.glUniform1i(self.program.uniformLocation('surfaceTexture'),0)
            gl.glDrawArrays(0x0004,0,self.vertex_count)
            self.program.release(); self.buffer.release(); self.vao.release()
            if gl.glGetError()!=0: raise RuntimeError('OpenGL drawing failed; using software preview.')
            self.frame_count+=1
            self.owner.compass.update()
            self.caption.setText('Preview · Exports retain full block detail')
        except Exception as exc:
            self.report_failure(exc)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.hint.setGeometry(24,14,max(1,self.width()-48),30)
        self.caption.setGeometry(24,self.height()-42,max(1,self.width()-48),30)

    def mousePressEvent(self,event):
        self.owner.mousePressEvent(event); self.update()

    def mouseReleaseEvent(self,event):
        self.owner.mouseReleaseEvent(event); self.update()

    def mouseMoveEvent(self,event):
        self.owner.mouseMoveEvent(event); self.update()

    def wheelEvent(self,event):
        self.owner.wheelEvent(event); self.update()

    def mouseDoubleClickEvent(self,event):
        self.owner.mouseDoubleClickEvent(event); self.update()
