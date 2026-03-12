"""
PHINS Ledger Backup Service
============================
Comprehensive backup service for all ledger and transaction data.

Features:
- Automatic backup before critical operations
- Scheduled periodic backups
- Transaction-level backup for rollback support
- Multi-store backup (foundations, billing, transactions)
- Data integrity verification
"""

import os
import json
import shutil
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import logging
import threading
import time

logger = logging.getLogger('phins.ledger_backup')


class LedgerBackupService:
    """
    Central backup service for all ledger and financial data.
    
    Provides:
    - Automatic backups before mutations
    - Periodic scheduled backups
    - Transaction checkpointing
    - Cross-service data backup
    """
    
    def __init__(self, backup_base_dir: str = None):
        """
        Initialize backup service.
        
        Args:
            backup_base_dir: Base directory for all backups
        """
        if backup_base_dir is None:
            workspace = os.environ.get('WORKSPACE_PATH', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            backup_base_dir = os.path.join(workspace, 'data', 'backups')
        
        self.backup_base_dir = backup_base_dir
        self.ledger_backup_dir = os.path.join(backup_base_dir, 'ledgers')
        self.transaction_backup_dir = os.path.join(backup_base_dir, 'transactions')
        self.foundation_backup_dir = os.path.join(backup_base_dir, 'foundations')
        self.billing_backup_dir = os.path.join(backup_base_dir, 'billing')
        
        # Create all directories
        for dir_path in [
            self.ledger_backup_dir,
            self.transaction_backup_dir,
            self.foundation_backup_dir,
            self.billing_backup_dir
        ]:
            os.makedirs(dir_path, exist_ok=True)
        
        # Transaction checkpoints for rollback
        self._checkpoints: Dict[str, Dict[str, Any]] = {}
        
        # Backup configuration
        self.max_backups = 50
        self.backup_interval_seconds = 300  # 5 minutes
        
        # Background backup thread
        self._backup_thread = None
        self._stop_backup_thread = False
        
        logger.info(f"Ledger backup service initialized: {backup_base_dir}")
    
    def backup_foundation_ledger(
        self,
        foundation_data: Dict[str, Any],
        label: str = None
    ) -> str:
        """
        Backup foundation ledger data.
        
        Args:
            foundation_data: Complete foundation data to backup
            label: Optional label for this backup
            
        Returns:
            Backup ID
        """
        timestamp = datetime.now(timezone.utc)
        backup_id = f"FND-{timestamp.strftime('%Y%m%d_%H%M%S')}"
        if label:
            backup_id = f"{backup_id}_{label}"
        
        backup_path = os.path.join(self.foundation_backup_dir, f"{backup_id}.json")
        
        backup_record = {
            'backup_id': backup_id,
            'timestamp': timestamp.isoformat(),
            'label': label,
            'data': foundation_data,
            'checksum': self._compute_data_checksum(foundation_data)
        }
        
        self._save_json(backup_path, backup_record)
        logger.info(f"Foundation ledger backup created: {backup_id}")
        
        # Cleanup old backups
        self._cleanup_old_backups(self.foundation_backup_dir, self.max_backups)
        
        return backup_id
    
    def backup_transaction_ledger(
        self,
        ledger_data: Dict[str, Any],
        label: str = None
    ) -> str:
        """
        Backup transaction ledger data.
        
        Args:
            ledger_data: Transaction ledger to backup
            label: Optional label
            
        Returns:
            Backup ID
        """
        timestamp = datetime.now(timezone.utc)
        backup_id = f"TXN-{timestamp.strftime('%Y%m%d_%H%M%S')}"
        if label:
            backup_id = f"{backup_id}_{label}"
        
        backup_path = os.path.join(self.transaction_backup_dir, f"{backup_id}.json")
        
        backup_record = {
            'backup_id': backup_id,
            'timestamp': timestamp.isoformat(),
            'label': label,
            'data': ledger_data,
            'checksum': self._compute_data_checksum(ledger_data),
            'transaction_count': len(ledger_data) if isinstance(ledger_data, dict) else 0
        }
        
        self._save_json(backup_path, backup_record)
        logger.info(f"Transaction ledger backup created: {backup_id}")
        
        self._cleanup_old_backups(self.transaction_backup_dir, self.max_backups)
        
        return backup_id
    
    def backup_billing_data(
        self,
        billing_data: Dict[str, Any],
        label: str = None
    ) -> str:
        """
        Backup billing data.
        
        Args:
            billing_data: Billing records to backup
            label: Optional label
            
        Returns:
            Backup ID
        """
        timestamp = datetime.now(timezone.utc)
        backup_id = f"BILL-{timestamp.strftime('%Y%m%d_%H%M%S')}"
        if label:
            backup_id = f"{backup_id}_{label}"
        
        backup_path = os.path.join(self.billing_backup_dir, f"{backup_id}.json")
        
        backup_record = {
            'backup_id': backup_id,
            'timestamp': timestamp.isoformat(),
            'label': label,
            'data': billing_data,
            'checksum': self._compute_data_checksum(billing_data),
            'billing_count': len(billing_data) if isinstance(billing_data, dict) else 0
        }
        
        self._save_json(backup_path, backup_record)
        logger.info(f"Billing data backup created: {backup_id}")
        
        self._cleanup_old_backups(self.billing_backup_dir, self.max_backups)
        
        return backup_id
    
    def backup_all_ledgers(
        self,
        foundation_data: Dict[str, Any] = None,
        transaction_data: Dict[str, Any] = None,
        billing_data: Dict[str, Any] = None,
        label: str = None
    ) -> Dict[str, str]:
        """
        Create a comprehensive backup of all ledgers.
        
        Returns:
            Dictionary of backup IDs for each ledger type
        """
        timestamp = datetime.now(timezone.utc)
        backup_ids = {}
        
        if foundation_data is not None:
            backup_ids['foundation'] = self.backup_foundation_ledger(foundation_data, label)
        
        if transaction_data is not None:
            backup_ids['transaction'] = self.backup_transaction_ledger(transaction_data, label)
        
        if billing_data is not None:
            backup_ids['billing'] = self.backup_billing_data(billing_data, label)
        
        # Create a master backup manifest
        master_backup_id = f"MASTER-{timestamp.strftime('%Y%m%d_%H%M%S')}"
        if label:
            master_backup_id = f"{master_backup_id}_{label}"
        
        manifest = {
            'master_backup_id': master_backup_id,
            'timestamp': timestamp.isoformat(),
            'label': label,
            'backup_ids': backup_ids,
            'status': 'complete'
        }
        
        manifest_path = os.path.join(self.ledger_backup_dir, f"{master_backup_id}_manifest.json")
        self._save_json(manifest_path, manifest)
        
        backup_ids['master'] = master_backup_id
        logger.info(f"Master backup created: {master_backup_id}")
        
        return backup_ids
    
    def create_checkpoint(
        self,
        checkpoint_id: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Create a transaction checkpoint for potential rollback.
        
        Args:
            checkpoint_id: Unique identifier for this checkpoint
            data: Data state to checkpoint
        """
        self._checkpoints[checkpoint_id] = {
            'checkpoint_id': checkpoint_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'data': json.loads(json.dumps(data, default=str)),  # Deep copy
            'checksum': self._compute_data_checksum(data)
        }
        
        logger.debug(f"Checkpoint created: {checkpoint_id}")
    
    def rollback_to_checkpoint(
        self,
        checkpoint_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Rollback to a previous checkpoint.
        
        Args:
            checkpoint_id: Checkpoint to rollback to
            
        Returns:
            Data from checkpoint, or None if not found
        """
        checkpoint = self._checkpoints.get(checkpoint_id)
        if not checkpoint:
            logger.error(f"Checkpoint not found: {checkpoint_id}")
            return None
        
        logger.info(f"Rolling back to checkpoint: {checkpoint_id}")
        return checkpoint['data']
    
    def clear_checkpoint(self, checkpoint_id: str) -> None:
        """Clear a checkpoint after successful transaction."""
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]
            logger.debug(f"Checkpoint cleared: {checkpoint_id}")
    
    def list_backups(
        self,
        backup_type: str = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        List available backups.
        
        Args:
            backup_type: Filter by type (foundation, transaction, billing, master)
            limit: Maximum number to return
            
        Returns:
            List of backup metadata
        """
        backups = []
        
        type_dirs = {
            'foundation': self.foundation_backup_dir,
            'transaction': self.transaction_backup_dir,
            'billing': self.billing_backup_dir,
            'master': self.ledger_backup_dir
        }
        
        dirs_to_scan = [type_dirs[backup_type]] if backup_type else list(type_dirs.values())
        
        for dir_path in dirs_to_scan:
            if not os.path.exists(dir_path):
                continue
            
            for filename in os.listdir(dir_path):
                if filename.endswith('.json'):
                    file_path = os.path.join(dir_path, filename)
                    try:
                        with open(file_path, 'r') as f:
                            data = json.load(f)
                            backups.append({
                                'backup_id': data.get('backup_id') or data.get('master_backup_id'),
                                'timestamp': data.get('timestamp'),
                                'label': data.get('label'),
                                'type': self._get_backup_type(filename),
                                'file_path': file_path
                            })
                    except Exception as e:
                        logger.error(f"Error reading backup {filename}: {e}")
        
        # Sort by timestamp descending
        backups.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return backups[:limit]
    
    def restore_backup(
        self,
        backup_id: str,
        backup_type: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Restore data from a backup.
        
        Args:
            backup_id: ID of backup to restore
            backup_type: Type of backup (foundation, transaction, billing)
            
        Returns:
            Restored data, or None if not found
        """
        backups = self.list_backups(backup_type)
        
        for backup in backups:
            if backup['backup_id'] == backup_id:
                file_path = backup['file_path']
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        
                    # Verify checksum
                    stored_checksum = data.get('checksum')
                    actual_checksum = self._compute_data_checksum(data.get('data', {}))
                    
                    if stored_checksum and stored_checksum != actual_checksum:
                        logger.warning(f"Backup checksum mismatch: {backup_id}")
                    
                    logger.info(f"Restored backup: {backup_id}")
                    return data.get('data')
                    
                except Exception as e:
                    logger.error(f"Error restoring backup {backup_id}: {e}")
                    return None
        
        logger.error(f"Backup not found: {backup_id}")
        return None
    
    def start_periodic_backup(
        self,
        get_data_func: Callable[[], Dict[str, Any]],
        interval_seconds: int = None
    ) -> None:
        """
        Start periodic background backups.
        
        Args:
            get_data_func: Function that returns data to backup
            interval_seconds: Backup interval in seconds
        """
        if interval_seconds:
            self.backup_interval_seconds = interval_seconds
        
        if self._backup_thread is not None and self._backup_thread.is_alive():
            logger.warning("Periodic backup already running")
            return
        
        self._stop_backup_thread = False
        
        def backup_loop():
            while not self._stop_backup_thread:
                try:
                    time.sleep(self.backup_interval_seconds)
                    if self._stop_backup_thread:
                        break
                    
                    data = get_data_func()
                    self.backup_all_ledgers(
                        foundation_data=data.get('foundation'),
                        transaction_data=data.get('transaction'),
                        billing_data=data.get('billing'),
                        label='periodic'
                    )
                except Exception as e:
                    logger.error(f"Error in periodic backup: {e}")
        
        self._backup_thread = threading.Thread(target=backup_loop, daemon=True)
        self._backup_thread.start()
        logger.info(f"Periodic backup started (interval: {self.backup_interval_seconds}s)")
    
    def stop_periodic_backup(self) -> None:
        """Stop periodic background backups."""
        self._stop_backup_thread = True
        if self._backup_thread:
            self._backup_thread.join(timeout=5)
            self._backup_thread = None
        logger.info("Periodic backup stopped")
    
    def _save_json(self, file_path: str, data: Dict) -> None:
        """Save data to JSON file with atomic write."""
        temp_path = file_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(temp_path, file_path)
    
    def _compute_data_checksum(self, data: Any) -> str:
        """Compute checksum for data integrity verification."""
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]
    
    def _get_backup_type(self, filename: str) -> str:
        """Determine backup type from filename."""
        if filename.startswith('FND-'):
            return 'foundation'
        elif filename.startswith('TXN-'):
            return 'transaction'
        elif filename.startswith('BILL-'):
            return 'billing'
        elif filename.startswith('MASTER-'):
            return 'master'
        return 'unknown'
    
    def _cleanup_old_backups(self, dir_path: str, keep: int) -> None:
        """Remove old backups, keeping only the most recent ones."""
        try:
            files = []
            for filename in os.listdir(dir_path):
                if filename.endswith('.json'):
                    file_path = os.path.join(dir_path, filename)
                    files.append((file_path, os.path.getmtime(file_path)))
            
            # Sort by modification time descending
            files.sort(key=lambda x: x[1], reverse=True)
            
            # Remove files beyond the keep limit
            for file_path, _ in files[keep:]:
                os.remove(file_path)
                logger.debug(f"Removed old backup: {file_path}")
                
        except Exception as e:
            logger.error(f"Error cleaning up backups: {e}")


# Singleton instance
_backup_service: Optional[LedgerBackupService] = None


def get_backup_service(backup_base_dir: str = None) -> LedgerBackupService:
    """Get or create the backup service singleton."""
    global _backup_service
    if _backup_service is None:
        _backup_service = LedgerBackupService(backup_base_dir)
    return _backup_service


def reset_backup_service() -> None:
    """Reset the backup service (for testing)."""
    global _backup_service
    if _backup_service:
        _backup_service.stop_periodic_backup()
    _backup_service = None
