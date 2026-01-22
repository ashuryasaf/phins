"""
PHINS Foundation Persistence Service
=====================================
Handles persistent storage of foundation data to ensure data survives restarts.

Features:
- Automatic save on every mutation operation
- Load data on startup
- Backup before major operations
- Data integrity validation
- Transaction logging
"""

import os
import json
import shutil
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger('phins.foundation_persistence')


class FoundationPersistenceService:
    """
    Persistence layer for Foundation data.
    
    Saves and loads foundation data to/from JSON files to ensure
    data survives server restarts.
    """
    
    def __init__(self, data_dir: str = None):
        """
        Initialize persistence service.
        
        Args:
            data_dir: Directory to store data files. Defaults to workspace/data/foundations
        """
        if data_dir is None:
            # Default to data/foundations in workspace
            workspace = os.environ.get('WORKSPACE_PATH', '/workspace')
            data_dir = os.path.join(workspace, 'data', 'foundations')
        
        self.data_dir = data_dir
        self.backup_dir = os.path.join(data_dir, 'backups')
        
        # Ensure directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        # Data file paths
        self.foundations_file = os.path.join(data_dir, 'foundations.json')
        self.members_file = os.path.join(data_dir, 'members.json')
        self.funds_file = os.path.join(data_dir, 'funds.json')
        self.contributions_file = os.path.join(data_dir, 'contributions.json')
        self.invitations_file = os.path.join(data_dir, 'invitations.json')
        self.votes_file = os.path.join(data_dir, 'votes.json')
        self.vote_casts_file = os.path.join(data_dir, 'vote_casts.json')
        self.claims_file = os.path.join(data_dir, 'claims.json')
        self.activities_file = os.path.join(data_dir, 'activities.json')
        self.ledger_file = os.path.join(data_dir, 'foundation_ledger.json')
        self.billing_integration_file = os.path.join(data_dir, 'billing_integration.json')
        
        # Track last save timestamp
        self.last_save = None
        
        logger.info(f"Foundation persistence initialized: {data_dir}")
    
    def save_all(self, data: Dict[str, Dict]) -> bool:
        """
        Save all foundation data to disk.
        
        Args:
            data: Dictionary containing all data stores:
                - foundations: Dict[str, Dict]
                - members: Dict[str, Dict]
                - funds: Dict[str, Dict]
                - contributions: Dict[str, Dict]
                - invitations: Dict[str, Dict]
                - votes: Dict[str, Dict]
                - vote_casts: Dict[str, Dict]
                - claims: Dict[str, Dict]
                - activities: Dict[str, Dict]
                
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create backup first
            self.create_backup()
            
            # Save each data store
            file_mapping = {
                'foundations': self.foundations_file,
                'members': self.members_file,
                'funds': self.funds_file,
                'contributions': self.contributions_file,
                'invitations': self.invitations_file,
                'votes': self.votes_file,
                'vote_casts': self.vote_casts_file,
                'claims': self.claims_file,
                'activities': self.activities_file
            }
            
            for key, file_path in file_mapping.items():
                if key in data:
                    self._save_json(file_path, data[key])
            
            # Save ledger if provided
            if 'ledger' in data:
                self._save_json(self.ledger_file, data['ledger'])
            
            # Save billing integration records if provided
            if 'billing_integration' in data:
                self._save_json(self.billing_integration_file, data['billing_integration'])
            
            self.last_save = datetime.now(timezone.utc).isoformat()
            logger.info(f"All foundation data saved at {self.last_save}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving foundation data: {e}")
            return False
    
    def load_all(self) -> Dict[str, Dict]:
        """
        Load all foundation data from disk.
        
        Returns:
            Dictionary containing all data stores
        """
        data = {
            'foundations': self._load_json(self.foundations_file) or {},
            'members': self._load_json(self.members_file) or {},
            'funds': self._load_json(self.funds_file) or {},
            'contributions': self._load_json(self.contributions_file) or {},
            'invitations': self._load_json(self.invitations_file) or {},
            'votes': self._load_json(self.votes_file) or {},
            'vote_casts': self._load_json(self.vote_casts_file) or {},
            'claims': self._load_json(self.claims_file) or {},
            'activities': self._load_json(self.activities_file) or {},
            'ledger': self._load_json(self.ledger_file) or {},
            'billing_integration': self._load_json(self.billing_integration_file) or {}
        }
        
        logger.info(f"Loaded foundation data: {len(data['foundations'])} foundations, "
                   f"{len(data['members'])} members, {len(data['contributions'])} contributions")
        
        return data
    
    def create_backup(self, label: str = None) -> str:
        """
        Create a backup of all current data.
        
        Args:
            label: Optional label for the backup
            
        Returns:
            Path to backup directory
        """
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        backup_name = f"backup_{timestamp}"
        if label:
            backup_name = f"{label}_{timestamp}"
        
        backup_path = os.path.join(self.backup_dir, backup_name)
        os.makedirs(backup_path, exist_ok=True)
        
        # Copy all data files
        files_to_backup = [
            self.foundations_file,
            self.members_file,
            self.funds_file,
            self.contributions_file,
            self.invitations_file,
            self.votes_file,
            self.vote_casts_file,
            self.claims_file,
            self.activities_file,
            self.ledger_file,
            self.billing_integration_file
        ]
        
        for file_path in files_to_backup:
            if os.path.exists(file_path):
                dest = os.path.join(backup_path, os.path.basename(file_path))
                shutil.copy2(file_path, dest)
        
        # Create backup manifest
        manifest = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'label': label,
            'files': [os.path.basename(f) for f in files_to_backup if os.path.exists(f)],
            'checksum': self._compute_backup_checksum(backup_path)
        }
        self._save_json(os.path.join(backup_path, 'manifest.json'), manifest)
        
        logger.info(f"Backup created: {backup_path}")
        
        # Clean up old backups (keep last 10)
        self._cleanup_old_backups(keep=10)
        
        return backup_path
    
    def restore_backup(self, backup_name: str) -> bool:
        """
        Restore data from a backup.
        
        Args:
            backup_name: Name of backup directory
            
        Returns:
            True if successful
        """
        backup_path = os.path.join(self.backup_dir, backup_name)
        if not os.path.exists(backup_path):
            logger.error(f"Backup not found: {backup_path}")
            return False
        
        try:
            # Verify checksum
            manifest_path = os.path.join(backup_path, 'manifest.json')
            if os.path.exists(manifest_path):
                manifest = self._load_json(manifest_path)
                expected_checksum = manifest.get('checksum')
                actual_checksum = self._compute_backup_checksum(backup_path)
                if expected_checksum != actual_checksum:
                    logger.warning(f"Backup checksum mismatch - may be corrupted")
            
            # Restore files
            for filename in os.listdir(backup_path):
                if filename == 'manifest.json':
                    continue
                src = os.path.join(backup_path, filename)
                dest = os.path.join(self.data_dir, filename)
                shutil.copy2(src, dest)
            
            logger.info(f"Restored backup: {backup_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            return False
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups."""
        backups = []
        
        if not os.path.exists(self.backup_dir):
            return backups
        
        for name in os.listdir(self.backup_dir):
            backup_path = os.path.join(self.backup_dir, name)
            if os.path.isdir(backup_path):
                manifest_path = os.path.join(backup_path, 'manifest.json')
                manifest = self._load_json(manifest_path) if os.path.exists(manifest_path) else {}
                
                backups.append({
                    'name': name,
                    'timestamp': manifest.get('timestamp'),
                    'label': manifest.get('label'),
                    'files': manifest.get('files', []),
                    'path': backup_path
                })
        
        # Sort by timestamp descending
        backups.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return backups
    
    def _save_json(self, file_path: str, data: Dict) -> None:
        """Save data to JSON file with atomic write."""
        # Write to temp file first
        temp_path = file_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        # Atomic rename
        os.replace(temp_path, file_path)
    
    def _load_json(self, file_path: str) -> Optional[Dict]:
        """Load data from JSON file."""
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Error loading JSON from {file_path}: {e}")
            return None
    
    def _compute_backup_checksum(self, backup_path: str) -> str:
        """Compute checksum of backup for integrity verification."""
        hasher = hashlib.sha256()
        
        for filename in sorted(os.listdir(backup_path)):
            if filename == 'manifest.json':
                continue
            file_path = os.path.join(backup_path, filename)
            if os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    hasher.update(f.read())
        
        return hasher.hexdigest()[:16]
    
    def _cleanup_old_backups(self, keep: int = 10) -> None:
        """Remove old backups, keeping only the most recent ones."""
        backups = self.list_backups()
        
        if len(backups) > keep:
            for backup in backups[keep:]:
                backup_path = backup['path']
                try:
                    shutil.rmtree(backup_path)
                    logger.info(f"Removed old backup: {backup['name']}")
                except Exception as e:
                    logger.error(f"Error removing backup {backup['name']}: {e}")
    
    def validate_data_integrity(self, data: Dict[str, Dict]) -> Tuple[bool, List[str]]:
        """
        Validate data integrity across all stores.
        
        Returns:
            Tuple of (is_valid, list of issues)
        """
        issues = []
        
        foundations = data.get('foundations', {})
        members = data.get('members', {})
        funds = data.get('funds', {})
        contributions = data.get('contributions', {})
        
        # Validate foundation references
        for member_id, member in members.items():
            foundation_id = member.get('foundation_id')
            if foundation_id and foundation_id not in foundations:
                issues.append(f"Member {member_id} references non-existent foundation {foundation_id}")
        
        # Validate fund references
        for fund_id, fund in funds.items():
            foundation_id = fund.get('foundation_id')
            if foundation_id and foundation_id not in foundations:
                issues.append(f"Fund {fund_id} references non-existent foundation {foundation_id}")
        
        # Validate contribution references
        for contrib_id, contrib in contributions.items():
            fund_id = contrib.get('fund_id')
            if fund_id and fund_id not in funds:
                issues.append(f"Contribution {contrib_id} references non-existent fund {fund_id}")
        
        # Validate member counts
        for foundation_id, foundation in foundations.items():
            expected_count = foundation.get('current_members', 0)
            actual_count = sum(
                1 for m in members.values()
                if m.get('foundation_id') == foundation_id and m.get('status') == 'active'
            )
            if expected_count != actual_count:
                issues.append(
                    f"Foundation {foundation_id} member count mismatch: "
                    f"expected {expected_count}, found {actual_count}"
                )
        
        # Validate fund balances
        for foundation_id, foundation in foundations.items():
            expected_balance = foundation.get('total_fund_balance', 0)
            actual_balance = sum(
                float(f.get('balance', 0))
                for f in funds.values()
                if f.get('foundation_id') == foundation_id
            )
            if abs(expected_balance - actual_balance) > 0.01:
                issues.append(
                    f"Foundation {foundation_id} balance mismatch: "
                    f"expected {expected_balance}, found {actual_balance}"
                )
        
        return len(issues) == 0, issues


# Singleton instance
_persistence_service: Optional[FoundationPersistenceService] = None


def get_persistence_service(data_dir: str = None) -> FoundationPersistenceService:
    """Get or create the persistence service singleton."""
    global _persistence_service
    if _persistence_service is None:
        _persistence_service = FoundationPersistenceService(data_dir)
    return _persistence_service


def reset_persistence_service() -> None:
    """Reset the persistence service (for testing)."""
    global _persistence_service
    _persistence_service = None
