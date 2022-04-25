from __future__ import annotations
from pathlib import Path
from typing import Callable
from warnings import warn
from qtpy.QtWidgets import QFileDialog, QLineEdit, QVBoxLayout, QHBoxLayout, QWidget, QMenu, QLabel, QSpinBox
from qtpy.QtGui import QCursor
from typing import Union
from .._categories import CATEGORIES, Category, filter_categories
from ._button_grid import ButtonGrid
from ._category_widget import make_gui_for_category
from napari.viewer import Viewer

class Assistant(QWidget):
    """The main Assistant widget.

    The widget holds buttons with icons to create widgets for the various
    cel operation categories.  It tracks which layers are connected to which
    widgets, and can export the state of the task graph to a dask graph
    or to jython code.

    Parameters
    ----------
    napari_viewer : Viewer
        This viewer instance will be provided by napari when it gets added
        as a plugin dock widget.
    """

    def __init__(self, napari_viewer: Viewer):

        super().__init__()
        self._viewer = napari_viewer
        napari_viewer.layers.events.removed.connect(self._on_layer_removed)
        napari_viewer.layers.selection.events.changed.connect(self._on_selection)
        self._layers = {}

        # visualize intermediate results human-readable from top-left to bottom-right
        self._viewer.grid.stride = -1

        CATEGORIES["Generate code..."] = self._code_menu
        CATEGORIES["Undo/Redo"] = self._undo_redo_menu
        CATEGORIES["Save and load workflows"] = self._workflow_menu

        CATEGORIES["Search napari hub"] = self.search_napari_hub
        CATEGORIES["Search image.sc"] = self.search_image_sc
        CATEGORIES["Search BIII"] = self.search_biii

        # build GUI
        icon_grid = ButtonGrid(self)
        icon_grid.addItems(CATEGORIES)
        icon_grid.itemClicked.connect(self._on_item_clicked)

        self.seach_field = QLineEdit("")
        def text_changed(*args, **kwargs):
            search_string = self.seach_field.text().lower()
            icon_grid.clear()
            icon_grid.addItems(filter_categories(search_string))

        self.seach_field.textChanged.connect(text_changed)
        text_changed()

        # create menu
        self.actions = [
            ("Export Python script to file", self.to_python),
            ("Export Jupyter Notebook", self.to_notebook),
            ("Copy to clipboard", self.to_clipboard),
        ]

        # create workflow menu
        self.workflow_actions = [
                                 ("Export workflow to file", self.to_file),
                                 ("Load workflow from file", self.load_workflow)
        ]

        self.undo_redo_actions =[
            ("Undo", self.undo_action),
            ("Redo", self.redo_action)
        ]

        # add Send to script editor menu in case it's installed
        try:
            import napari_script_editor
            self.actions.append(("Send to Script Editor", self.to_script_editor))
        except ImportError:
            pass

        self.setLayout(QVBoxLayout())
        search_and_help = QWidget()
        search_and_help.setLayout(QHBoxLayout())
        from ._button_grid import _get_icon
        help = QLabel("?")
        help.setToolTip(
            '<html>'
            'Use the search field on the left to enter a term describing the function you would like to apply to your image.\n'
            'Searching will limit the number of shown categories and listed operations.\n'
            '<br><br>The icons in the buttons below denote the processed image types:\n'
            '<br><img src="' + _get_icon("intensity_image") + '" width="24" heigth="24"> In <b>intensity images</b> the pixel value represents a measurement, e.g. of collected light during acquisition in a microscope.\n'
            '<br><img src="' + _get_icon("binary_image") + '" width="24" heigth="24"> In <b>binary images</b> pixels with value 0 mean there is no object present. All other pixels (typically value 1) represent any object.\n'
            '<br><img src="' + _get_icon("label_image") + '" width="24" heigth="24"> In <b>label images</b> the integer pixel intensity corresponds to the object identity. E.g. all pixels of object 2 have value 2.\n'
            '<br><img src="' + _get_icon("parametric_image") + '" width="24" heigth="24"> In <b>parametric images</b> the pixel value represents an object measurement. All pixels of an object can for example contain the same value, e.g. the objects circularity or area.\n'
            '<br><img src="' + _get_icon("mesh_image") + '" width="24" heigth="24"> In <b>mesh images</b> we can visualize connectivity between objects and distances as intensity along lines.\n'
            '<br><img src="' + _get_icon("any_image") + '" width="24" heigth="24"> This icon means one can use <b>any kind of image</b> for this operation.'
            '</html>'
        )
        help.setMaximumWidth(20)
        search_and_help.layout().addWidget(self.seach_field)
        search_and_help.layout().addWidget(help)

        self.layout().addWidget(search_and_help)
        self.layout().addWidget(icon_grid)

        self.button_size_spin_box = QSpinBox()
        self.button_size_spin_box.setValue(40)
        self.button_size_spin_box.setToolTip("Size of buttons in operation widgets (temporary GUI)")
        self.layout().addWidget(self.button_size_spin_box)

        self.layout().setContentsMargins(5, 5, 5, 5)
        self.setMinimumWidth(345)

    def _code_menu(self):
        menu = QMenu(self)

        for name, cb in self.actions:
            submenu = menu.addAction(name)
            submenu.triggered.connect(cb)

        menu.move(QCursor.pos())
        menu.show()

    def _workflow_menu(self):
        menu = QMenu(self)

        for name, cb in self.workflow_actions:
            submenu = menu.addAction(name)
            submenu.triggered.connect(cb)

        menu.move(QCursor.pos())
        menu.show()

    def _undo_redo_menu(self):
        menu = QMenu(self)

        for name, cb in self.undo_redo_actions :
            submenu = menu.addAction(name)
            submenu.triggered.connect(cb)

        menu.move(QCursor.pos())
        menu.show()

    def _on_selection(self, event):
        for layer, (dw, gui) in self._layers.items():
            if layer in self._viewer.layers.selection:
                dw.show()
            else:
                dw.hide()

    def _on_active_layer_change(self, event):
        for layer, (dw, gui) in self._layers.items():
            dw.show() if event.value is layer else dw.hide()

    def _on_layer_removed(self, event):
        layer = event.value
        if layer in self._layers:
            dw = self._layers[layer][0]
            try:
                self._viewer.window.remove_dock_widget(dw)
            except KeyError:
                pass
            # remove layer from internal list
            self._layers.pop(layer)

    def _on_item_clicked(self, item):
        self._activate(CATEGORIES.get(item.text()))

    def _get_active_layer(self):
        return self._viewer.layers.selection.active

    def _activate(self, category = Union[Category, Callable]):
        if callable(category):
            category()
            return

        # get currently active layer (before adding dock widget)
        input_layer = self._get_active_layer()
        if not input_layer:
            warn("Please select a layer first")
            return False

        # make a new widget
        gui = make_gui_for_category(category, self.seach_field.text(), self._viewer, button_size=self.button_size_spin_box.value())
        # prevent auto-call when adding to the viewer, to avoid double calls
        # do this here rather than widget creation for the sake of
        # non-Assistant-based widgets.
        gui._auto_call = False
        # add gui to the viewer
        dw = self._viewer.window.add_dock_widget(gui, area="right", name=category.name)
        # workaround for https://github.com/napari/napari/issues/4348
        dw._close_btn = False
        # make sure the originally active layer is the input
        try:
            gui.input0.value = input_layer
        except ValueError:
            pass # this happens if input0 should be labels but we provide an image
        # call the function widget &
        # track the association between the layer and the gui that generated it
        self._layers[gui()] = (dw, gui)
        # turn on auto_call, and make sure that if the input changes we update
        gui._auto_call = True
        self._connect_to_all_layers()
        return gui

    def _refesh_data(self, event):
        self._refresh(event.source)

    def _refresh(self, changed_layer):
        """Goes through all layers and refreshs those which have changed_layer as input

        Parameters
        ----------
        changed_layer
        """
        for layer, (dw, mgui) in self._layers.items():
            for w in mgui:
                if w.value == changed_layer:
                    mgui()

    def _connect_to_all_layers(self):
        """Attach an event listener to all layers that are currently open in napari
        """
        for layer in self._viewer.layers:
            layer.events.data.disconnect(self._refesh_data)
            layer.events.data.connect(self._refesh_data)

    def load_sample_data(self, fname="Lund_000500_resampled-cropped.tif"):
        data_dir = Path(__file__).parent.parent / "data"
        self._viewer.open(str(data_dir / fname))

    def _id_to_name(self, id, dict):
        if id not in dict.keys():
            new_name = "image" + str(len(dict.keys()))
            dict[id] = new_name
        return dict[id]

    def to_python(self, filename=None):
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(self, "Save code as...", ".", "*.py")
        #return Pipeline.from_assistant(self).to_jython(filename)

        from napari_workflows import WorkflowManager
        manager = WorkflowManager.install(self._viewer)
        code = manager.to_python_code()

        if filename:
            filename = Path(filename).expanduser().resolve()
            filename.write_text(code)


    def to_notebook(self, filename=None, execute=True):
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(self, "Save code as notebook...", ".", "*.ipynb")
        #return Pipeline.from_assistant(self).to_notebook(filename)

        from napari_workflows import WorkflowManager
        manager = WorkflowManager.install(self._viewer)
        code = manager.to_python_code(notebook=True)

        import jupytext

        # jython code is created in the jupytext light format
        # https://jupytext.readthedocs.io/en/latest/formats.html#the-light-format

        jt = jupytext.reads(code, fmt="py:light")
        nb = jupytext.writes(jt, fmt="ipynb")
        if filename:
            filename = Path(filename).expanduser().resolve()
            filename.write_text(nb)
            # could use a NamedTemporaryFile to run this even without write
            if execute:
                from subprocess import Popen
                from shutil import which

                executable = "jupyter-lab"
                if not which(executable):
                    executable = "jupyter-notebook"
                    if not which(executable):
                        raise RuntimeError("Cannot find jupyter-lab or jupyter-notebook executable. Please install it using pip install jupyterlab")

                try:
                    Popen([executable, "-y", str(filename)])
                except Exception as e:
                    warn(f"Failed to execute notebook: {e}")
        return nb


    def to_clipboard(self):
        import pyperclip

        from napari_workflows import WorkflowManager
        manager = WorkflowManager.install(self._viewer)
        pyperclip.copy(manager.to_python_code())

    def to_script_editor(self):
        import napari_script_editor
        editor = napari_script_editor.ScriptEditor.get_script_editor_from_viewer(self._viewer)

        from napari_workflows import WorkflowManager
        manager = WorkflowManager.install(self._viewer)
        editor.set_code(manager.to_python_code())

    def to_file(self, filename=None):
        from napari_workflows import WorkflowManager, _io_yaml_v1

        if not filename:
            filename, _ = QFileDialog.getSaveFileName(self, "Export workflow ...", ".", "*.yaml")

        # get the workflow, should one be installed
        workflow_manager = WorkflowManager.install(self._viewer)
        _io_yaml_v1.save_workflow(filename, workflow_manager.workflow)

    def load_workflow(self, filename=None):
        from napari_workflows import _io_yaml_v1
        from .. _workflow_io_utility import initialise_root_functions, load_remaining_workflow
        import warnings

        layer_names = [str(lay) for lay in self._viewer.layers]
        if not layer_names:
            warnings.warn("No images opened. Please open an image before loading the workflow!")
            return

        if not filename:
            filename, _ = QFileDialog.getOpenFileName(self, "Import workflow ...", ".", "*.yaml")
        self.workflow = _io_yaml_v1.load_workflow(filename)

        w_dw = initialise_root_functions(
            self.workflow, 
            self._viewer, 
            button_size= self.button_size_spin_box.value(),
        )
        w_dw += load_remaining_workflow(
            self.workflow, 
            self._viewer,
            button_size=self.button_size_spin_box.value(),
        )

        for gui, dw in w_dw:
            self._layers[gui()] = (dw, gui)

        self._viewer.layers.select_previous()
        self._viewer.layers.select_next()

    def undo_action(self):
        from .._undo_redo import delete_workflow_widgets_layers
        from .._workflow_io_utility import initialise_root_functions, load_remaining_workflow
        from napari_workflows import WorkflowManager

        # install the workflow manager and get the current workflow and controller
        manager = WorkflowManager.install(self._viewer)
        workflow = manager.workflow
        controller = manager.undo_redo_controller

        print('workflow before undo:')
        print(workflow)

        # only reload if there is an undo to be performed
        if controller.undo_stack:

            # undo workflow step: workflow is now the undone workflow
            controller.undo()
            print('workflow after undo:')
            print(workflow)

            controller.freeze = True

            delete_workflow_widgets_layers(self._viewer)

            w_dw = initialise_root_functions(
                workflow, 
                self._viewer, 
                button_size= self.button_size_spin_box.value(),
            )
            w_dw += load_remaining_workflow(
                workflow, 
                self._viewer,
                button_size=self.button_size_spin_box.value(),
            )
            print('tried to load widgets')
            for gui, dw in w_dw:
                self._layers[gui()] = (dw, gui)

            self._viewer.layers.select_previous()
            self._viewer.layers.select_next()

            controller.freeze = False
            print('unfrozen')
        

    def redo_action(self):
        return

    def search_napari_hub(self):
        print("Search napari hub")
        from urllib.parse import quote
        _open_url("https://www.napari-hub.org/?search=" + quote(self.seach_field.text()) + "&sort=relevance")

    def search_image_sc(self):
        print("Search image sc")
        from urllib.parse import quote
        _open_url("https://forum.image.sc/search?q=napari%20" + quote(self.seach_field.text()))

    def search_biii(self):
        print("Search biii")
        from urllib.parse import quote
        _open_url("https://biii.eu/search?search_api_fulltext=napari%20" + quote(self.seach_field.text()))


def _open_url(url):
    import webbrowser
    webbrowser.open(url, new=0, autoraise=True)
