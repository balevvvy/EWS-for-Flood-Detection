import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("StatusClassifier")

class StatusAlertManager:
    def __init__(self):
        """
        Manajer untuk klasifikasi status dan pengiriman alert.
        Pada fase ini, fungsi utamanya adalah mendeteksi transisi status dan mencatat log.
        Pengiriman alert sesungguhnya (Telegram/Webhook) akan diimplementasikan di Fase 2.
        """
        self.last_status = None
        
    def process_status(self, current_status):
        """
        Menerima status dari PixelToStatusMapper dan memicu alert jika status berubah.
        """
        if current_status == "UNKNOWN (Belum Dikalibrasi)":
            return current_status
            
        if current_status != self.last_status:
            logger.info(f"STATUS BERUBAH: {self.last_status} -> {current_status}")
            
            if current_status == "SIAGA":
                self._trigger_alert(current_status, "Level air mencapai batas MERAH (Darurat)!")
            elif current_status == "WASPADA":
                self._trigger_alert(current_status, "Level air mencapai batas KUNING (Waspada).")
            elif current_status == "NORMAL" and self.last_status is not None:
                self._trigger_alert(current_status, "Level air kembali normal (di bawah kuning).")
                
            self.last_status = current_status
            
        return current_status
        
    def _trigger_alert(self, status, message):
        """
        Fungsi placeholder untuk pengiriman notifikasi ke pihak eksternal.
        """
        logger.warning(f"[ALERT Triggered] [{status}] {message}")
        # TODO: Implementasi logika webhook / notifikasi Telegram di sini
