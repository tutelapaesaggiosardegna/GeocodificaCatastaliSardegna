# -*- coding: utf-8 -*-
"""
Modulo download/estrazione dataset catastale - Plugin Geocodifica Catastali
"""

import os
import zipfile
import requests
from qgis.PyQt import QtWidgets

# URL dataset catastale
DATASET_URL = "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/GetDataset.php?dataset=SARDEGNA.zip"

# Cartella di destinazione relativa al plugin
PLUGIN_DIR = os.path.dirname(__file__)
DEST_DIR = PLUGIN_DIR  # i dati saranno salvati in PLUGIN_DIR/Sardegna


def scarica_e_scompatta_dataset(url=DATASET_URL, dest_dir=DEST_DIR, dialog_ui=None):
    """
    Scarica il dataset catastale e lo estrae mantenendo la gerarchia:
    Sardegna -> Province -> Comuni.
    Aggiorna la progressBar della UI passata come dialog_ui.
    """

    try:
        if dialog_ui and hasattr(dialog_ui, "progressBar"):
            dialog_ui.progressBar.setValue(0)
            dialog_ui.progressBar.setFormat("Download in corso...")

            # Disabilita i pulsanti durante l'operazione
            if hasattr(dialog_ui, "buttonBox"):
                dialog_ui.buttonBox.setDisabled(True)

        os.makedirs(dest_dir, exist_ok=True)
        zip_path = os.path.join(dest_dir, "SARDEGNA.zip")

        # --- Scaricamento con avanzamento ---
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and dialog_ui and hasattr(dialog_ui, "progressBar"):
                        percent = int(downloaded * 50 / total_size)  # 0-50% download
                        dialog_ui.progressBar.setValue(percent)
                        QtWidgets.QApplication.processEvents()

        # --- Estrazione ZIP principale ---
        sardegna_dir = os.path.join(dest_dir, "Sardegna")
        os.makedirs(sardegna_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            file_list = zip_ref.namelist()
            total_files = len(file_list)
            for i, file in enumerate(file_list, start=1):
                zip_ref.extract(file, sardegna_dir)
                if dialog_ui and hasattr(dialog_ui, "progressBar"):
                    percent = 50 + int(i * 40 / total_files)  # 50-90% estrazione principale
                    dialog_ui.progressBar.setValue(percent)
                    QtWidgets.QApplication.processEvents()

        # --- Estrazione ricorsiva ---
        if dialog_ui and hasattr(dialog_ui, "progressBar"):
            dialog_ui.progressBar.setFormat("Estrazione archivi annidati...")
        estrai_zip_annidati(sardegna_dir, dialog_ui)

        os.remove(zip_path)

        if dialog_ui and hasattr(dialog_ui, "progressBar"):
            dialog_ui.progressBar.setValue(100)
            dialog_ui.progressBar.setFormat("Completato!")

            # Riabilita i pulsanti al termine
            if hasattr(dialog_ui, "buttonBox"):
                dialog_ui.buttonBox.setDisabled(False)

        return True

    except Exception as e:
        if dialog_ui and hasattr(dialog_ui, "progressBar"):
            dialog_ui.progressBar.setValue(0)

            # Riabilita i pulsanti anche in caso di errore
            if hasattr(dialog_ui, "buttonBox"):
                dialog_ui.buttonBox.setDisabled(False)

        QtWidgets.QMessageBox.critical(dialog_ui, "Errore", f"Errore durante il download/estrazione:\n{e}")
        return False


def estrai_zip_annidati(directory, dialog_ui=None):
    """
    Estrae ricorsivamente tutti i file .zip annidati.
    Aggiorna la progressBar se disponibile.
    """
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".zip"):
                zip_path = os.path.join(root, file)
                nome_cartella = os.path.splitext(file)[0]
                dest_folder = os.path.join(root, nome_cartella)
                try:
                    os.makedirs(dest_folder, exist_ok=True)
                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        zip_ref.extractall(dest_folder)
                    os.remove(zip_path)

                    if dialog_ui and hasattr(dialog_ui, "progressBar"):
                        dialog_ui.progressBar.setFormat(f"Estrazione: {file}")
                        QtWidgets.QApplication.processEvents()

                    estrai_zip_annidati(dest_folder, dialog_ui)
                except Exception as e:
                    print(f"Errore estraendo {zip_path}: {e}")
