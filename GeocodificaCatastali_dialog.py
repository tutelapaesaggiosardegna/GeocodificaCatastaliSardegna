# -*- coding: utf-8 -*-
"""
Dialog del plugin - Geocodifica Catastali
- OK NON chiude il dialog: esegue run_script() e lascia la finestra aperta
- Annulla chiude la finestra
- Il nome del layer include anche il nome del comune
- Rimozione dei standardButtons e creazione pulsanti custom per evitare qualunque auto-accept
"""

import os
from qgis.PyQt import uic, QtWidgets, QtCore
import geopandas as gpd
from qgis.core import QgsVectorLayer, QgsProject

# Cartella del plugin e base dati relativa
PLUGIN_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.join(PLUGIN_DIR, "Sardegna")

# Carica la UI dal file .ui creato con Qt Designer
FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "GeocodificaIndirizzo_dialog_base.ui")
)

def _read_text(widget):
    """Ritorna testo da QLineEdit o QComboBox (vuoto se widget mancante)."""
    if widget is None:
        return ""
    if isinstance(widget, QtWidgets.QComboBox):
        return (widget.currentText() or "").strip()
    if isinstance(widget, QtWidgets.QLineEdit):
        return (widget.text() or "").strip()
    return ""

class GeocodificaIndirizzoDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # Dialog non-modale e non autocancellante
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        # --- PULSANTI: elimina gli standardButtons e crea bottoni custom ---
        if hasattr(self, "buttonBox"):
            self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.NoButton)

            self.okButton = QtWidgets.QPushButton("OK", self)
            self.buttonBox.addButton(self.okButton, QtWidgets.QDialogButtonBox.ActionRole)
            self.okButton.clicked.connect(self.on_ok_clicked)

            self.cancelButton = QtWidgets.QPushButton("Annulla", self)
            self.buttonBox.addButton(self.cancelButton, QtWidgets.QDialogButtonBox.RejectRole)
            self.cancelButton.clicked.connect(self.reject)

            # Scollega qualsiasi accepted/rejected residuo
            try:
                self.buttonBox.accepted.disconnect()
            except Exception:
                pass
            try:
                self.buttonBox.rejected.disconnect()
            except Exception:
                pass
            # Per ulteriore robustezza, intercetta click dell'OK del box (se presente)
            ok_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
            if ok_btn:
                try:
                    ok_btn.clicked.disconnect()
                except Exception:
                    pass
                ok_btn.clicked.connect(self.on_ok_clicked)

        # Pulsante di esecuzione dedicato (se presente nella UI)
        if hasattr(self, "runButton"):
            self.runButton.clicked.connect(self.run_script)

    # Non lasciamo che accept() chiuda la finestra
    def accept(self):
        # Esegue la logica ma NON chiude
        self.on_ok_clicked()

    # Ulteriore guardia: ignora qualunque "Accepted" che dovesse arrivare
    def done(self, r):
        if r == QtWidgets.QDialog.Accepted:
            # ignora chiusura implicita
            return
        super().done(r)

    # --- Click su OK: esegue lo script e resta nella finestra ---
    def on_ok_clicked(self):
        self.run_script()  # La GUI resta aperta in ogni caso

    def run_script(self) -> bool:
        """
        Valida input, legge GML, filtra/interseca e carica il layer.
        Ritorna True se tutto OK; False altrimenti. La finestra resta aperta.
        """
        # Verifica elementi UI necessari (combinazioni possibili: *Edit o *Combo)
        provincia = _read_text(getattr(self, "provinciaCombo", None)) or _read_text(getattr(self, "provinciaEdit", None))
        comune = _read_text(getattr(self, "comuneCombo", None)) or _read_text(getattr(self, "comuneEdit", None))
        foglio = _read_text(getattr(self, "foglioEdit", None))
        particella = _read_text(getattr(self, "particellaEdit", None))

        # Validazione input (la finestra RESTA aperta)
        if not all([provincia, comune, foglio, particella]):
            QtWidgets.QMessageBox.warning(self, "Input Mancante",
                                          "Si prega di inserire tutti i dati richiesti.")
            return False

        # Percorso cartella del comune
        base_dir = BASE_DIR
        comune_dir = os.path.join(base_dir, provincia, comune)
        if not os.path.isdir(comune_dir):
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           f"Cartella comune non trovata:\n{comune_dir}")
            return False

        # Ricerca file *_map.gml e *_ple.gml
        map_file, ple_file = None, None
        try:
            for f in os.listdir(comune_dir):
                if f.endswith("_map.gml"):
                    map_file = os.path.join(comune_dir, f)
                elif f.endswith("_ple.gml"):
                    ple_file = os.path.join(comune_dir, f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore lettura cartella",
                                           f"Impossibile leggere il contenuto di:\n{comune_dir}\n\nDettagli: {e}")
            return False

        if not map_file or not ple_file:
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           "File catastali '_map.gml' o '_ple.gml' non trovati nella cartella.")
            return False

        # Lettura GML
        try:
            gdf_map = gpd.read_file(map_file)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           f"Errore caricamento file map:\n{map_file}\n\nDettagli: {e}")
            return False

        try:
            gdf_ple = gpd.read_file(ple_file)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           f"Errore caricamento file ple:\n{ple_file}\n\nDettagli: {e}")
            return False

        # Filtra foglio e particella
        foglio_sel = gdf_map[gdf_map.get("LABEL", None) == str(foglio)]
        if foglio_sel is None or foglio_sel.empty:
            QtWidgets.QMessageBox.warning(self, "Foglio non trovato",
                                          f"Foglio '{foglio}' non presente nel file '_map.gml'.")
            return False

        particella_sel = gdf_ple[gdf_ple.get("LABEL", None) == str(particella)]
        if particella_sel is None or particella_sel.empty:
            QtWidgets.QMessageBox.warning(self, "Particella non trovata",
                                          f"Particella '{particella}' non presente nel file '_ple.gml'.")
            return False

        # Intersezione spaziale
        try:
            particella_in_foglio = gpd.overlay(particella_sel, foglio_sel, how="intersection")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore spaziale",
                                           f"Errore durante l'intersezione spaziale:\n{e}")
            return False

        if particella_in_foglio.empty:
            QtWidgets.QMessageBox.warning(self, "Errore spaziale",
                                          "La particella selezionata non ricade nel foglio indicato.")
            return False

        # Scrive un GPKG temporaneo nel comune (sovrascrive se presente)
        temp_path = os.path.join(comune_dir, "particella_sel.gpkg")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

        try:
            particella_in_foglio.to_file(temp_path, driver="GPKG")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore salvataggio",
                                           f"Errore nel salvataggio del GeoPackage:\n{temp_path}\n\nDettagli: {e}")
            return False

        # Carica il layer in QGIS (INCLUDE il nome del comune)
        layer_name = f"{comune}-F.{foglio}-P.{particella}"
        layer = QgsVectorLayer(temp_path, layer_name, "ogr")
        if not layer or not layer.isValid():
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           "Errore nel caricamento del layer in QGIS.")
            return False

        QgsProject.instance().addMapLayer(layer)
        QtWidgets.QMessageBox.information(self, "Successo",
                                          f"Layer '{layer_name}' caricato correttamente.")
        # La finestra resta aperta
        return True
