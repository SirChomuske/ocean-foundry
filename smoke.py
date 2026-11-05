"""Headless smoke checks for the native executable (`--smoke-test` family).

These are verification harnesses, not application features: they drive the real
main window, wait for the first generated surface and optionally perform a bake
or a few GPU frames before writing a report next to the app.
"""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
FLAGS = ('--smoke-test', '--gpu-smoke-test', '--bake-smoke-test')


def enabled(argv=None):
    argv = sys.argv if argv is None else argv
    return any(flag in argv for flag in FLAGS)


def start(application, window):
    """Attach the timed checks to a shown window; the caller runs the event loop."""
    argv = sys.argv
    smoke_frames = 0
    bake_started = False
    smoke_preview = window.preview

    def timeout():
        gpu = smoke_preview.gpu
        report = {'status': window.status.text(), 'has_result': window.result is not None,
                  'jobs': len(window.jobs), 'generating': window.generating, 'smoke_frames': smoke_frames,
                  'gpu_error': window.preview.gpu_error, 'gpu_ready': gpu.ready if gpu else False,
                  'gpu_frames': gpu.frame_count if gpu else 0, 'renderer': gpu.renderer if gpu else ''}
        report_dir = ROOT / '.build'
        report_dir.mkdir(exist_ok=True)
        (report_dir / 'smoke-timeout.json').write_text(json.dumps(report, indent=2))
        application.exit(2)

    def finish():
        nonlocal smoke_frames, bake_started
        if window.result is None or window.jobs:
            QTimer.singleShot(300, finish)
            return
        if '--bake-smoke-test' in argv:
            if not bake_started:
                bake_started = True
                window.colour_controls['enabled'].setChecked(True)
                window.control_tabs.setCurrentIndex(1)
                if any(flag in argv for flag in ('--fft-normal-test', '--procedural-test', '--ocean-library-test')):
                    window.material_mode.setCurrentIndex(0)
                    window.appearance_controls['normal_source'].setCurrentIndex(0)
                    model = window.appearance_controls['surface_model']
                    model.setCurrentIndex(model.findData('ocean_maps' if '--ocean-library-test' in argv
                                                         else 'procedural' if '--procedural-test' in argv
                                                         else 'fft_normals'))
                if '--lava-normal-test' in argv:
                    window.material_mode.setCurrentIndex(window.material_mode.findData('lava'))
                if '--gpu-smoke-test' in argv:
                    window.appearance_controls['gpu'].setChecked(True)
                window.start_bake()
                QTimer.singleShot(300, finish)
                return
            if window.baking:
                QTimer.singleShot(300, finish)
                return
            if not window.result.get('procedural'):
                (ROOT / 'error.log').write_text(window.status.text())
                application.exit(5)
                return
        gpu = smoke_preview.gpu
        if '--gpu-smoke-test' in argv:
            if gpu is None or gpu.error:
                (ROOT / 'error.log').write_text('GPU smoke test failed: ' + window.preview.gpu_error)
                application.exit(3)
                return
            # Windows hides a windowed executable launched by the test harness,
            # so it may never receive normal paint events. Request a real
            # framebuffer render instead of waiting on them.
            gpu.grabFramebuffer()
            if not gpu.ready or not gpu.frame_count:
                QTimer.singleShot(100, finish)
                return
            if smoke_frames < 12:
                smoke_preview.yaw += .03
                gpu.update()
                smoke_frames += 1
                QTimer.singleShot(30, finish)
                return
        window.grab().save(str(ROOT / 'preview.png'))
        report = {'renderer': gpu.renderer if gpu else 'Software',
                  'gpu_frames': gpu.frame_count if gpu else 0,
                  'mesh_uploads': gpu.upload_count if gpu else 0,
                  'bake_backend': window.result.get('bake_backend'),
                  'bake_seconds': window.result.get('bake_seconds'),
                  'surface_mode': window.active_mode}
        report_dir = ROOT / '.build'
        report_dir.mkdir(exist_ok=True)
        (report_dir / 'smoke-test.json').write_text(json.dumps(report, indent=2))
        print('PASS native window, generated surface, preview render', flush=True)
        window.close()

    QTimer.singleShot(700, finish)
    QTimer.singleShot(30000, timeout)
