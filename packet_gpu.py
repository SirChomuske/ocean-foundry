"""OpenGL 3 packet evaluation using float targets, with no vendor-specific API."""
import ctypes
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QVector4D, QOpenGLContext
from PySide6.QtOpenGL import (QOpenGLShaderProgram, QOpenGLShader, QOpenGLTexture,
                             QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat)
import water_packets


class PacketGPU:
    def __init__(self, gl, vertex):
        self.gl = gl
        self.program = QOpenGLShaderProgram()
        fragment = '''#version 130
uniform sampler2D coordinates;
uniform vec4 dims,climate;
uniform float surfaceAngle,microDetail;
uniform int patternSeed;
out vec4 outputFields;
''' + water_packets.GLSL + '''
void main(){outputFields=packets(texelFetch(coordinates,ivec2(gl_FragCoord.xy),0).xy);}
'''
        for kind, source in ((QOpenGLShader.ShaderTypeBit.Vertex, vertex), (QOpenGLShader.ShaderTypeBit.Fragment, fragment)):
            if not self.program.addShaderFromSourceCode(kind, source):
                raise RuntimeError(self.program.log())
        if not self.program.link():
            raise RuntimeError(self.program.log())
        # QImage conversion would clamp signed float slopes. Read the float FBO.
        address=QOpenGLContext.currentContext().getProcAddress('glReadPixels')
        if not address:raise RuntimeError('Float surface readback unavailable')
        signature=ctypes.WINFUNCTYPE(None,*([ctypes.c_int]*4+[ctypes.c_uint]*2+[ctypes.c_void_p]))
        self.read=signature(address)

    def fields(self, x, z, scale, angle, disorder, seed, micro, footprint):
        rows, cols = x.shape
        data = np.zeros((rows, cols, 4), np.float32)
        data[:,:,0], data[:,:,1] = x, z
        tex = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        fbo = None
        try:
            tex.setFormat(QOpenGLTexture.TextureFormat.RGBA32F)
            tex.setSize(cols, rows); tex.setMipLevels(1)
            tex.allocateStorage(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.Float32)
            tex.setData(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.Float32, data.tobytes())
            tex.setMinMagFilters(QOpenGLTexture.Filter.Nearest, QOpenGLTexture.Filter.Nearest)
            fmt = QOpenGLFramebufferObjectFormat(); fmt.setInternalTextureFormat(0x8814)
            fbo = QOpenGLFramebufferObject(QSize(cols, rows), fmt)
            if not fbo.isValid():
                raise RuntimeError('Float surface target unavailable')
            fbo.bind(); tex.bind(0)
            gl = self.gl; gl.glViewport(0, 0, cols, rows)
            gl.glDisable(0x0BE2); gl.glDisable(0x0B71)
            p = self.program; p.bind()
            p.setUniformValue(p.uniformLocation('dims'), QVector4D(footprint, footprint, 1, 1))
            p.setUniformValue(p.uniformLocation('climate'), QVector4D(0, 0, scale, disorder))
            gl.glUniform1i(p.uniformLocation('coordinates'), 0)
            gl.glUniform1i(p.uniformLocation('patternSeed'), seed)
            gl.glUniform1f(p.uniformLocation('surfaceAngle'), angle)
            gl.glUniform1f(p.uniformLocation('microDetail'), micro)
            gl.glDrawArrays(0x0004, 0, 3)
            output = np.empty_like(data)
            self.read(0, 0, cols, rows, 0x1908, 0x1406, output.ctypes.data)
            if gl.glGetError() or not np.isfinite(output).all():
                raise RuntimeError('Float surface readback failed')
            return tuple(output[:,:,i].copy() for i in range(4))
        finally:
            self.program.release()
            if fbo is not None: fbo.release()
            tex.destroy()

    def close(self):
        self.program.removeAllShaders()
