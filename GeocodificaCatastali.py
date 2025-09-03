# -*- coding: utf-8 -*-
"""
Plugin QGIS - Geocodifica Catastali
(seleziona particelle multiple separate da virgola)
"""

import os
import re
import datetime
from qgis.PyQt import QtWidgets, uic
from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsFields,
    QgsField,
    QgsWkbTypes,
)
from PyQt5.QtCore import QVariant
import geopandas as gpd

# Importa funzione scarica ed estrai dataset catastale
from .scarica_dati import scarica_e_scompatta_dataset

# Percorso base relativo alla cartella del plugin
PLUGIN_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.join(PLUGIN_DIR, 'Sardegna')

# Caricamento del file UI creato con Qt Designer
FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'GeocodificaIndirizzo_dialog_base.ui')
)

# ----------------- Utility per colonne/CRS -----------------

def _pick_column(df, aliases):
    """
    Restituisce il nome della prima colonna in df che corrisponde (case-insensitive)
    a uno degli alias forniti. Gestisce eventuali suffissi '_1', '_2' tipici di overlay.
    """
    cols = list(df.columns)

    def base_name(name: str) -> str:
        n = name.lower()
        for suf in ("_1", "_2"):
            if n.endswith(suf):
                return n[:-len(suf)]
        return n

    aliases_low = [a.lower() for a in aliases]

    # Match diretto sull'elenco colonne (dopo normalizzazione)
    for col in cols:
        if base_name(col) in aliases_low:
            return col

    # Fallback: match "contains" per maggiore tolleranza
    for col in cols:
        b = base_name(col)
        if any(b == a or a in b for a in aliases_low):
            return col

    return None


def _friendly_cols(df):
    """Ritorna stringa con l'elenco delle colonne (per messaggi d'errore)."""
    return ", ".join(map(str, df.columns))


# ----------------- Dialog principale -----------------

class GeocodificaCatastaliDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super(GeocodificaCatastaliDialog, self).__init__(parent)
        self.setupUi(self)

        # --- Evita chiusura automatica su OK ---
        if hasattr(self, "buttonBox"):
            try:
                self.buttonBox.accepted.disconnect()
            except Exception:
                pass
            try:
                self.buttonBox.rejected.disconnect()
            except Exception:
                pass
            self.buttonBox.accepted.connect(self.on_ok_clicked)  # NON chiude
            self.buttonBox.rejected.connect(self.reject)         # Chiude

        # Progress bar nascosta quando non serve
        if hasattr(self, "progressBar"):
            self.progressBar.hide()

        # Campo percorso base bloccato (solo informativo)
        if hasattr(self, 'baseDirEdit'):
            self.baseDirEdit.setDisabled(True)
            self.baseDirEdit.setText(BASE_DIR)

        # Inizializzazione controlli
        if hasattr(self, 'provinciaCombo'):
            self.provinciaCombo.clear()
            self.provinciaCombo.addItem("")  # riga vuota
        if hasattr(self, 'comuneCombo'):
            self.comuneCombo.clear()
            self.comuneCombo.addItem("")     # riga vuota

        # Campo foglio: pulizia + placeholder (NUOVO)
        if hasattr(self, 'foglioEdit'):
            self.foglioEdit.clear()
            self.foglioEdit.setPlaceholderText("digitare il nome del foglio ...")

        # Campo particelle: pulizia + placeholder già previsto
        if hasattr(self, 'particellaEdit'):
            self.particellaEdit.clear()
            self.particellaEdit.setPlaceholderText("digitare n. particella/e (separate da una virgola) ...")

        # Collegamenti dipendenze tra campi
        if hasattr(self, 'provinciaCombo'):
            self.provinciaCombo.currentIndexChanged.connect(self.on_provincia_changed)
        if hasattr(self, 'comuneCombo'):
            self.comuneCombo.currentIndexChanged.connect(self.on_comune_changed)

        # Pulsante "Scarica Dati"
        if hasattr(self, 'scaricaDatiBtn'):
            self.scaricaDatiBtn.clicked.connect(self.scarica_dati)

        # Mostra ultima data aggiornamento
        self.mostra_data_ultimo_aggiornamento()

        # Popola province senza auto-selezionare
        self.carica_province()

    # Intercetta l'OK del buttonBox: NON chiude il dialog
    def on_ok_clicked(self):
        self.run_geocoding()

    # Non chiudere se qualcuno chiama accept()
    def accept(self):
        self.run_geocoding()

    # Ripristina lo stato iniziale dei campi/controlli
    def reset_fields(self):
        if hasattr(self, 'provinciaCombo'):
            self.provinciaCombo.blockSignals(True)
            self.provinciaCombo.clear()
            self.provinciaCombo.addItem("")
            self.provinciaCombo.setCurrentIndex(0)
            self.provinciaCombo.blockSignals(False)

        if hasattr(self, 'comuneCombo'):
            self.comuneCombo.blockSignals(True)
            self.comuneCombo.clear()
            self.comuneCombo.addItem("")
            self.comuneCombo.setCurrentIndex(0)
            self.comuneCombo.blockSignals(False)

        # Foglio: pulizia + placeholder (NUOVO)
        if hasattr(self, 'foglioEdit'):
            self.foglioEdit.clear()
            self.foglioEdit.setPlaceholderText("digitare il nome del foglio ...")

        # Particelle: pulizia + placeholder
        if hasattr(self, 'particellaEdit'):
            self.particellaEdit.clear()
            self.particellaEdit.setPlaceholderText("digitare n. particella/e (separate da una virgola) ...")

        if hasattr(self, 'progressBar'):
            self.progressBar.hide()
            self.progressBar.setValue(0)

        self.mostra_data_ultimo_aggiornamento()
        self.carica_province()

    # Su chiusura finestra: reset e chiusura base
    def closeEvent(self, event):
        try:
            self.reset_fields()
        finally:
            super().closeEvent(event)

    # Su "Annulla": reset e chiusura
    def reject(self):
        self.reset_fields()
        super().reject()

    # Cambio provincia: svuota elenco comuni e azzera campi
    def on_provincia_changed(self):
        if hasattr(self, 'comuneCombo'):
            self.comuneCombo.blockSignals(True)
            self.comuneCombo.clear()
            self.comuneCombo.addItem("")  # riga vuota
            self.comuneCombo.setCurrentIndex(0)
            self.comuneCombo.blockSignals(False)

        # Foglio: pulizia + placeholder (NUOVO)
        if hasattr(self, 'foglioEdit'):
            self.foglioEdit.clear()
            self.foglioEdit.setPlaceholderText("digitare il nome del foglio ...")

        # Particelle: pulizia + placeholder
        if hasattr(self, 'particellaEdit'):
            self.particellaEdit.clear()
            self.particellaEdit.setPlaceholderText("digitare n. particella/e (separate da una virgola) ...")

        self.carica_comuni(popola_senza_selezionare=True)

    # Cambio comune: azzera campi foglio/particelle
    def on_comune_changed(self):
        # Foglio: pulizia + placeholder (NUOVO)
        if hasattr(self, 'foglioEdit'):
            self.foglioEdit.clear()
            self.foglioEdit.setPlaceholderText("digitare il nome del foglio ...")

        # Particelle: pulizia + placeholder
        if hasattr(self, 'particellaEdit'):
            self.particellaEdit.clear()
            self.particellaEdit.setPlaceholderText("digitare n. particella/e (separate da una virgola) ...")

    # Aggiorna la label dell'ultimo aggiornamento o la progressBar come fallback
    def mostra_data_ultimo_aggiornamento(self):
        sardegna_dir = BASE_DIR
        testo = 'Premi il tasto "Aggiorna i dati" per scaricare i dati!'

        try:
            if os.path.isdir(sardegna_dir):
                with os.scandir(sardegna_dir) as it:
                    if any(it):
                        mtime = os.path.getmtime(sardegna_dir)
                        ultima_data = datetime.datetime.fromtimestamp(mtime)
                        testo = f"Dati AdE aggiornati al {ultima_data.strftime('%d/%m/%Y %H:%M')}"
        except Exception:
            pass

        if hasattr(self, "lastUpdateLabel"):
            self.lastUpdateLabel.setText(testo)
        elif hasattr(self, "progressBar"):
            self.progressBar.setVisible(True)
            self.progressBar.setFormat(testo)
            self.progressBar.setValue(0 if 'Aggiorna i dati' in testo else 100)

    # Popola l'elenco province (senza selezione automatica)
    def carica_province(self):
        if not hasattr(self, 'provinciaCombo'):
            return
        self.provinciaCombo.blockSignals(True)
        try:
            self.provinciaCombo.clear()
            self.provinciaCombo.addItem("")
            if not os.path.isdir(BASE_DIR):
                return
            province = [d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d))]
            province.sort()
            self.provinciaCombo.addItems(province)
            self.provinciaCombo.setCurrentIndex(0)
        finally:
            self.provinciaCombo.blockSignals(False)

    # Popola l'elenco dei comuni per la provincia selezionata (senza selezione automatica)
    def carica_comuni(self, popola_senza_selezionare: bool = False):
        if not hasattr(self, 'comuneCombo') or not hasattr(self, 'provinciaCombo'):
            return
        self.comuneCombo.blockSignals(True)
        try:
            self.comuneCombo.clear()
            self.comuneCombo.addItem("")
            provincia_selezionata = self.provinciaCombo.currentText().strip()
            if not provincia_selezionata:
                return
            provincia_dir = os.path.join(BASE_DIR, provincia_selezionata)
            if not os.path.isdir(provincia_dir):
                return
            comuni = [d for d in os.listdir(provincia_dir) if os.path.isdir(os.path.join(provincia_dir, d))]
            comuni.sort()
            self.comuneCombo.addItems(comuni)
            self.comuneCombo.setCurrentIndex(0)
        finally:
            self.comuneCombo.blockSignals(False)

    # ----------------- Logica principale -----------------

    def run_geocoding(self):
        """
        Esegue la ricerca della/e particella/e catastale/i e carica i risultati in QGIS.
        Supporta multiple particelle separate da virgola per lo stesso foglio.
        """
        codice_provincia = self.provinciaCombo.currentText().strip() if hasattr(self, 'provinciaCombo') else ""
        nome_comune = self.comuneCombo.currentText().strip() if hasattr(self, 'comuneCombo') else ""
        num_foglio = self.foglioEdit.text().strip() if hasattr(self, 'foglioEdit') else ""
        num_particella = self.particellaEdit.text().strip() if hasattr(self, 'particellaEdit') else ""

        # Validazione base dei campi richiesti
        if not all([codice_provincia, nome_comune, num_foglio, num_particella]):
            QtWidgets.QMessageBox.warning(self, "Input Mancante",
                                          "Si prega di inserire tutti i dati richiesti.")
            return

        # Verifica percorso comune
        comune_dir = os.path.join(BASE_DIR, codice_provincia, nome_comune)
        if not os.path.isdir(comune_dir):
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           f"La cartella specificata non esiste:\n{comune_dir}")
            return

        # Individuazione file catastali _map.gml e _ple.gml
        map_file, ple_file = None, None
        for filename in os.listdir(comune_dir):
            if filename.endswith('_map.gml'):
                map_file = os.path.join(comune_dir, filename)
            elif filename.endswith('_ple.gml'):
                ple_file = os.path.join(comune_dir, filename)

        if not map_file or not ple_file:
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           "File catastali '_map.gml' o '_ple.gml' non trovati nella cartella.")
            return

        # Lettura GML
        try:
            gdf_map = gpd.read_file(map_file)
            gdf_ple = gpd.read_file(ple_file)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           f"Errore caricamento file GML:\n{str(e)}")
            return

        # Risoluzione nomi colonna (FOGLIO e PARTICELLA)
        aliases_foglio = ["label", "foglio", "codfoglio", "cod_foglio", "num_foglio", "n_foglio", "foglio_n"]
        aliases_particella = ["label", "particella", "numero", "num_part", "n_part", "num_particella",
                              "ident", "identificativo", "id_particella"]

        col_foglio = _pick_column(gdf_map, aliases_foglio)
        if not col_foglio:
            QtWidgets.QMessageBox.critical(
                self, "Campo FOGLIO non trovato",
                "Impossibile individuare la colonna del FOGLIO nel file _map.gml.\n"
                f"Colonne disponibili: { _friendly_cols(gdf_map) }"
            )
            return

        col_part = _pick_column(gdf_ple, aliases_particella)
        if not col_part:
            QtWidgets.QMessageBox.critical(
                self, "Campo PARTICELLA non trovato",
                "Impossibile individuare la colonna della PARTICELLA nel file _ple.gml.\n"
                f"Colonne disponibili: { _friendly_cols(gdf_ple) }"
            )
            return

        # Copie minimali con rinomina per evitare suffissi dopo overlay
        gdf_map_min = gdf_map[[col_foglio, "geometry"]].copy().rename(columns={col_foglio: "FOGLIO"})
        gdf_ple_min = gdf_ple[[col_part, "geometry"]].copy().rename(columns={col_part: "PARTICELLA"})

        # Filtro FOGLIO
        foglio_sel = gdf_map_min[gdf_map_min["FOGLIO"].astype(str).str.strip() == str(num_foglio).strip()]
        if foglio_sel.empty:
            QtWidgets.QMessageBox.warning(
                self, "Foglio non trovato",
                f"Foglio '{num_foglio}' non trovato.\n"
                f"(Campo usato: FOGLIO; esempi presenti: "
                f"{', '.join(map(str, gdf_map_min['FOGLIO'].astype(str).unique()[:10]))} ... )"
            )
            return

        # Parsing particelle multiple (separate da virgola)
        particelle_list = [p.strip() for p in re.split(r',', num_particella) if p.strip()]
        if not particelle_list:
            QtWidgets.QMessageBox.warning(self, "Particelle non valide",
                                          "Inserire almeno una particella (separate da virgola).")
            return

        # Filtro PARTICELLA
        particella_sel = gdf_ple_min[gdf_ple_min["PARTICELLA"].astype(str).str.strip().isin(particelle_list)]
        if particella_sel.empty:
            QtWidgets.QMessageBox.warning(
                self, "Particelle non trovate",
                f"Nessuna delle particelle richieste ({', '.join(particelle_list)}) è presente."
            )
            return

        # Intersezione spaziale: particelle ∩ foglio
        try:
            particelle_in_foglio = gpd.overlay(particella_sel, foglio_sel, how='intersection')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Errore spaziale",
                                           f"Errore durante l'intersezione spaziale:\n{e}")
            return

        if particelle_in_foglio.empty:
            QtWidgets.QMessageBox.warning(self, "Errore spaziale",
                                          "Le particelle selezionate non ricadono nel foglio indicato.")
            return

        # Avviso su eventuali particelle richieste ma non intersecanti/assenti
        trovate = set(particelle_in_foglio["PARTICELLA"].astype(str).str.strip().unique())
        richieste = set(particelle_list)
        mancanti = richieste - trovate
        if mancanti:
            QtWidgets.QMessageBox.information(
                self, "Avviso",
                "Le seguenti particelle richieste non sono state trovate nel foglio o non intersecano: "
                + ", ".join(sorted(mancanti))
            )

        # ----------------- Creazione layer QGIS in memoria -----------------

        # Tipo geometrico: MultiPolygon se presente
        geom_types = particelle_in_foglio.geom_type.unique().tolist()
        if any(gt == 'MultiPolygon' for gt in geom_types):
            wkb_type = QgsWkbTypes.MultiPolygon
        elif any(gt == 'Polygon' for gt in geom_types):
            wkb_type = QgsWkbTypes.Polygon
        else:
            wkb_type = QgsWkbTypes.Unknown

        # CRS dal GeoDataFrame oppure EPSG:3003 come default prudenziale
        crs = particelle_in_foglio.crs.to_string() if particelle_in_foglio.crs else 'EPSG:3003'
        uri = f"{QgsWkbTypes.displayString(wkb_type)}?crs={crs}"

        # Nome layer: Comune + Foglio + elenco particelle realmente caricate
        particelle_label = ", ".join(sorted(trovate, key=lambda x: (len(x), x))) if trovate else num_particella
        layer_name = f"{nome_comune} - F. {num_foglio} - P. {particelle_label}"

        # Crea layer memoria e schema attributi
        mem_layer = QgsVectorLayer(uri, layer_name, "memory")
        provider = mem_layer.dataProvider()

        fields = QgsFields()
        for col_name, dtype in zip(particelle_in_foglio.columns, particelle_in_foglio.dtypes):
            if col_name == 'geometry':
                continue
            dtypestr = str(dtype)
            if 'int' in dtypestr:
                fields.append(QgsField(col_name, QVariant.Int))
            elif 'float' in dtypestr:
                fields.append(QgsField(col_name, QVariant.Double))
            else:
                fields.append(QgsField(col_name, QVariant.String))
        provider.addAttributes(fields)
        mem_layer.updateFields()

        # Inserimento feature dal GeoDataFrame
        features = []
        for _, row in particelle_in_foglio.iterrows():
            feat = QgsFeature()
            feat.setFields(mem_layer.fields())
            feat.setGeometry(QgsGeometry.fromWkt(row.geometry.wkt))
            attr_values = [row[col] for col in mem_layer.fields().names()]
            feat.setAttributes(attr_values)
            features.append(feat)

        provider.addFeatures(features)
        mem_layer.updateExtents()

        # Evita duplicati nel progetto: rimuove eventuali layer con lo stesso nome
        existing = [lyr for lyr in QgsProject.instance().mapLayers().values()
                    if lyr.name() == mem_layer.name()]
        for lyr in existing:
            QgsProject.instance().removeMapLayer(lyr.id())

        # Aggiunge il layer al progetto
        QgsProject.instance().addMapLayer(mem_layer)

        QtWidgets.QMessageBox.information(self, "Successo",
                                          f"Layer '{mem_layer.name()}' caricato correttamente.")

    # ----------------- Download/aggiornamento dati -----------------

    def scarica_dati(self):
        """Scarica ed estrae i dati catastali tramite pulsante UI."""

        # Disabilita rapidamente la UI per evitare interazioni durante l'operazione
        for obj in ('scaricaDatiBtn', 'buttonBox', 'provinciaCombo', 'comuneCombo', 'foglioEdit', 'particellaEdit'):
            if hasattr(self, obj):
                getattr(self, obj).setEnabled(False)

        QtWidgets.QApplication.processEvents()

        if hasattr(self, "progressBar"):
            self.progressBar.setValue(0)
            self.progressBar.show()

        if hasattr(self, "lastUpdateLabel"):
            self.lastUpdateLabel.setText("Aggiornamento in corso...")

        ok = scarica_e_scompatta_dataset(dialog_ui=self)

        # Ripristino della UI
        for obj in ('scaricaDatiBtn', 'buttonBox', 'provinciaCombo', 'comuneCombo', 'foglioEdit', 'particellaEdit'):
            if hasattr(self, obj):
                getattr(self, obj).setEnabled(True)

        if hasattr(self, "progressBar"):
            self.progressBar.hide()

        if ok:
            self.carica_province()
            self.mostra_data_ultimo_aggiornamento()
            QtWidgets.QMessageBox.information(self, "Completato",
                                              "Dati catastali scaricati e scompattati con successo.")
        else:
            QtWidgets.QMessageBox.critical(self, "Errore",
                                           "Errore durante download o estrazione dei dati catastali.")


# ----------------- Bootstrap plugin -----------------

class GeocodificaCatastali:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dialog = None
        self.action = None

    def initGui(self):
        from qgis.PyQt.QtGui import QIcon
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QtWidgets.QAction(QIcon(icon_path), "Geocodifica Catastali", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Geocodifica Catastali", self.action)

    def unload(self):
        self.iface.removePluginMenu("&Geocodifica Catastali", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        if self.dialog is None:
            self.dialog = GeocodificaCatastaliDialog()
            self.dialog.carica_province()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()