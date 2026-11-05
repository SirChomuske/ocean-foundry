"""Presentation-only localisation; setting keys and generator inputs stay unchanged."""
import json,os,re,sys
from pathlib import Path

LANGUAGE='en';CATALOG={};_installed=False;_translator=None

def text(value):
    if LANGUAGE!='zh_CN' or not isinstance(value,str) or not value:return value
    if value in ('Ocean Foundry','OCEAN FOUNDRY'):return value
    if value in CATALOG:return CATALOG[value]
    # Status strings combine translated phrases with numbers and user file names.
    return _pattern.sub(lambda m:CATALOG[m.group()],value) if _pattern else value

_pattern=None
def install(application,root):
    global LANGUAGE,CATALOG,_pattern,_installed,_translator
    if _installed:return
    config=Path(root)/'language.json'
    try:language=json.loads(config.read_text(encoding='utf-8')).get('language','en')
    except (OSError,ValueError,AttributeError):language='en'
    LANGUAGE=os.environ.get('OCEAN_FOUNDRY_LANGUAGE',language)
    if LANGUAGE!='zh_CN':return
    assets=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    CATALOG=json.loads((assets/'zh_CN.json').read_text(encoding='utf-8'))
    _pattern=re.compile(r'(?<![A-Za-z])(?:'+'|'.join(re.escape(k) for k in sorted(CATALOG,key=len,reverse=True))+r')(?![A-Za-z])')
    from PySide6 import QtWidgets as W
    from PySide6.QtCore import QTranslator,QLibraryInfo,QLocale
    from PySide6.QtGui import QPainter
    QLocale.setDefault(QLocale('zh_CN'))
    _translator=QTranslator(application)
    for base in (assets/'translations',Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))):
        if _translator.load(str(base/'qtbase_zh_CN.qm')):application.installTranslator(_translator);break
    def wrap(cls,name,indices=None):
        original=getattr(cls,name)
        def call(self,*args,**kwargs):
            args=list(args)
            for i in range(len(args)) if indices is None else indices:
                if i<len(args):args[i]=text(args[i])
            return original(self,*args,**kwargs)
        setattr(cls,name,call)
    for cls in (W.QLabel,W.QPushButton,W.QCheckBox,W.QGroupBox,W.QListWidgetItem):wrap(cls,'__init__',(0,))
    for cls in (W.QLabel,W.QAbstractButton,W.QListWidgetItem):wrap(cls,'setText',(0,))
    for cls,name in ((W.QGroupBox,'setTitle'),(W.QWidget,'setWindowTitle'),(W.QWidget,'setToolTip'),
                     (W.QComboBox,'addItem'),(W.QComboBox,'setItemText'),(W.QComboBox,'setCurrentText'),
                     (W.QTabWidget,'addTab'),(W.QFormLayout,'addRow'),(W.QFormLayout,'insertRow'),
                     (W.QListWidget,'addItem'),(QPainter,'drawText')):wrap(cls,name)
    # Dialog text is translated without modifying filenames or block identifiers.
    for cls,names,indices in ((W.QMessageBox,('warning','information','question','critical','about'),(1,2)),
                              (W.QFileDialog,('getOpenFileName','getSaveFileName'),(1,3)),
                              (W.QColorDialog,('getColor',),(2,))):
        for name in names:
            original=getattr(cls,name)
            def dialog(*args,_original=original,_indices=indices,_cls=cls,**kwargs):
                args=list(args)
                for i in _indices:
                    if i<len(args):args[i]=text(args[i])
                if _cls is W.QFileDialog:kwargs['options']=kwargs.get('options',W.QFileDialog.Option(0))|W.QFileDialog.Option.DontUseNativeDialog
                if _cls is W.QColorDialog:kwargs['options']=kwargs.get('options',W.QColorDialog.ColorDialogOption(0))|W.QColorDialog.ColorDialogOption.DontUseNativeDialog
                return _original(*args,**kwargs)
            setattr(cls,name,staticmethod(dialog))
    _installed=True
