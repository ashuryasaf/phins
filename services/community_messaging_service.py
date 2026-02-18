"""
PHINS Community Messaging Service
=================================

Real-time style community communication tool for foundation members.
Provides foundation-scoped discussion threads and member-to-member messages.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from services.foundation_service import get_foundation_service
from services.notification_service import (
    NotificationChannel,
    NotificationPriority,
    NotificationRequest,
    create_notification_service,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    token = uuid.uuid4().hex[:10].upper()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{token}"


class CommunityMessagingService:
    """
    Community messaging utility for member collaboration.

    Design notes:
    - Messages are scoped by foundation_id.
    - Only active foundation members can post/read.
    - Founder/admin can close discussions.
    """

    def __init__(self, foundation_service=None, notification_service=None):
        self._foundation_service = foundation_service or get_foundation_service()
        self._notification_service = notification_service or create_notification_service(use_mock=True)

        self._threads: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_thread(
        self,
        *,
        foundation_id: str,
        sender_user_id: str,
        title: str,
        message: str,
        tags: Optional[List[str]] = None,
        notify_members: bool = True,
    ) -> Dict[str, Any]:
        """Create a new discussion thread and the initial message."""
        if not title or not title.strip():
            return {"success": False, "error_code": "TITLE_REQUIRED", "error_message": "Thread title is required"}
        if not message or not message.strip():
            return {"success": False, "error_code": "MESSAGE_REQUIRED", "error_message": "Initial message is required"}

        member_result = self._require_active_member(foundation_id, sender_user_id)
        if not member_result[0]:
            return {"success": False, "error_code": "UNAUTHORIZED", "error_message": member_result[1]}
        member = member_result[2]
        assert member is not None

        thread_id = _generate_id("THR")
        created_at = _now_iso()
        normalized_tags = sorted({str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()})

        thread = {
            "thread_id": thread_id,
            "foundation_id": foundation_id,
            "title": title.strip(),
            "status": "open",
            "tags": normalized_tags,
            "created_by": sender_user_id,
            "created_by_member_id": member.get("id"),
            "created_by_display_name": member.get("display_name") or member.get("member_name") or sender_user_id,
            "created_at": created_at,
            "updated_at": created_at,
            "last_activity_at": created_at,
            "message_count": 0,
            "participants": [sender_user_id],
            "closed_at": None,
            "closed_by": None,
        }

        with self._lock:
            self._threads[thread_id] = thread
            first_message = self._append_message_locked(
                foundation_id=foundation_id,
                thread_id=thread_id,
                sender_user_id=sender_user_id,
                sender_member=member,
                content=message.strip(),
            )

        if notify_members:
            self._notify_other_members(
                foundation_id=foundation_id,
                sender_user_id=sender_user_id,
                subject=f"New community thread: {thread['title']}",
                content=(
                    f"A new community discussion was created in foundation {foundation_id}.\n"
                    f"Title: {thread['title']}\n"
                    f"By: {thread['created_by_display_name']}\n"
                ),
            )

        return {
            "success": True,
            "thread": thread.copy(),
            "message": first_message,
        }

    def list_threads(
        self,
        *,
        foundation_id: str,
        user_id: str,
        limit: int = 50,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List threads visible to a foundation member."""
        member_result = self._require_active_member(foundation_id, user_id)
        if not member_result[0]:
            return {"success": False, "error_code": "UNAUTHORIZED", "error_message": member_result[1]}

        with self._lock:
            threads = [
                t.copy()
                for t in self._threads.values()
                if t.get("foundation_id") == foundation_id
            ]

        if status:
            status_lower = status.strip().lower()
            threads = [thread for thread in threads if str(thread.get("status", "")).lower() == status_lower]

        threads.sort(key=lambda thread: thread.get("last_activity_at", ""), reverse=True)
        return {"success": True, "items": threads[: max(1, int(limit))], "total": len(threads)}

    def get_thread(
        self,
        *,
        foundation_id: str,
        user_id: str,
        thread_id: str,
        limit_messages: int = 200,
    ) -> Dict[str, Any]:
        """Get thread metadata and messages for a member."""
        member_result = self._require_active_member(foundation_id, user_id)
        if not member_result[0]:
            return {"success": False, "error_code": "UNAUTHORIZED", "error_message": member_result[1]}

        with self._lock:
            thread = self._threads.get(thread_id)
            if not thread or thread.get("foundation_id") != foundation_id:
                return {"success": False, "error_code": "NOT_FOUND", "error_message": "Thread not found"}

            messages = [
                msg.copy()
                for msg in self._messages.values()
                if msg.get("foundation_id") == foundation_id and msg.get("thread_id") == thread_id
            ]

        messages.sort(key=lambda item: item.get("created_at", ""))
        if limit_messages > 0:
            messages = messages[-int(limit_messages) :]
        return {"success": True, "thread": thread.copy(), "messages": messages, "count": len(messages)}

    def post_reply(
        self,
        *,
        foundation_id: str,
        thread_id: str,
        sender_user_id: str,
        content: str,
        notify_members: bool = True,
    ) -> Dict[str, Any]:
        """Post a reply in an existing discussion thread."""
        if not content or not content.strip():
            return {"success": False, "error_code": "MESSAGE_REQUIRED", "error_message": "Reply content is required"}

        member_result = self._require_active_member(foundation_id, sender_user_id)
        if not member_result[0]:
            return {"success": False, "error_code": "UNAUTHORIZED", "error_message": member_result[1]}
        member = member_result[2]
        assert member is not None

        with self._lock:
            thread = self._threads.get(thread_id)
            if not thread or thread.get("foundation_id") != foundation_id:
                return {"success": False, "error_code": "NOT_FOUND", "error_message": "Thread not found"}
            if thread.get("status") != "open":
                return {"success": False, "error_code": "THREAD_CLOSED", "error_message": "Thread is closed"}

            message = self._append_message_locked(
                foundation_id=foundation_id,
                thread_id=thread_id,
                sender_user_id=sender_user_id,
                sender_member=member,
                content=content.strip(),
            )

        if notify_members:
            self._notify_other_members(
                foundation_id=foundation_id,
                sender_user_id=sender_user_id,
                subject=f"New reply in: {thread.get('title', 'community thread')}",
                content=(
                    f"A new reply was posted in foundation {foundation_id}.\n"
                    f"Thread: {thread.get('title', 'community thread')}\n"
                    f"Sender: {member.get('display_name') or member.get('member_name') or sender_user_id}\n"
                ),
            )

        return {"success": True, "message": message}

    def close_thread(
        self,
        *,
        foundation_id: str,
        thread_id: str,
        actor_user_id: str,
    ) -> Dict[str, Any]:
        """Close a thread (creator/founder/admin only)."""
        member_result = self._require_active_member(foundation_id, actor_user_id)
        if not member_result[0]:
            return {"success": False, "error_code": "UNAUTHORIZED", "error_message": member_result[1]}
        actor_member = member_result[2]
        assert actor_member is not None

        with self._lock:
            thread = self._threads.get(thread_id)
            if not thread or thread.get("foundation_id") != foundation_id:
                return {"success": False, "error_code": "NOT_FOUND", "error_message": "Thread not found"}

            is_creator = thread.get("created_by") == actor_user_id
            is_admin = actor_member.get("role") in {"founder", "admin"}
            if not is_creator and not is_admin:
                return {
                    "success": False,
                    "error_code": "FORBIDDEN",
                    "error_message": "Only the creator, founder, or admin can close this thread",
                }

            thread["status"] = "closed"
            thread["closed_at"] = _now_iso()
            thread["closed_by"] = actor_user_id
            thread["updated_at"] = thread["closed_at"]

        return {"success": True, "thread": thread.copy()}

    def _append_message_locked(
        self,
        *,
        foundation_id: str,
        thread_id: str,
        sender_user_id: str,
        sender_member: Dict[str, Any],
        content: str,
    ) -> Dict[str, Any]:
        """Append a message while caller holds lock."""
        message_id = _generate_id("MSG")
        created_at = _now_iso()
        display_name = sender_member.get("display_name") or sender_member.get("member_name") or sender_user_id
        message = {
            "message_id": message_id,
            "foundation_id": foundation_id,
            "thread_id": thread_id,
            "sender_user_id": sender_user_id,
            "sender_member_id": sender_member.get("id"),
            "sender_display_name": display_name,
            "content": content,
            "created_at": created_at,
            "edited_at": None,
        }
        self._messages[message_id] = message

        thread = self._threads.get(thread_id)
        if thread:
            thread["message_count"] = int(thread.get("message_count", 0)) + 1
            thread["updated_at"] = created_at
            thread["last_activity_at"] = created_at
            participants = set(thread.get("participants", []))
            participants.add(sender_user_id)
            thread["participants"] = sorted(participants)

        return message

    def _require_active_member(
        self, foundation_id: str, user_id: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validate active member access for a foundation operation."""
        if not user_id:
            return False, "Authentication required", None
        member = self._foundation_service._get_member_by_user(foundation_id, user_id)
        if not member:
            return False, "You are not a member of this foundation", None
        if member.get("status") != "active":
            return False, "Only active members can use community messaging", None
        return True, "", member

    def _notify_other_members(
        self,
        *,
        foundation_id: str,
        sender_user_id: str,
        subject: str,
        content: str,
    ) -> None:
        """Best-effort member notifications about discussion activity."""
        try:
            members = self._foundation_service.get_foundation_members(foundation_id, include_pending=False)
            for member in members:
                if member.get("status") != "active":
                    continue
                if member.get("member_id") == sender_user_id:
                    continue
                email = member.get("email")
                if not email:
                    continue

                request = NotificationRequest(
                    channel=NotificationChannel.EMAIL,
                    recipient=email,
                    subject=subject,
                    content=content,
                    priority=NotificationPriority.LOW,
                    customer_id=str(member.get("member_id") or ""),
                    metadata={"source": "community_messaging"},
                )
                self._notification_service.send(request)
        except Exception:
            # This should never break thread creation/replies.
            pass


_community_messaging_service: Optional[CommunityMessagingService] = None


def get_community_messaging_service(
    foundation_service=None,
    notification_service=None,
) -> CommunityMessagingService:
    """Get singleton community messaging service."""
    global _community_messaging_service
    if _community_messaging_service is None:
        _community_messaging_service = CommunityMessagingService(
            foundation_service=foundation_service,
            notification_service=notification_service,
        )
    return _community_messaging_service


def reset_community_messaging_service() -> None:
    """Reset singleton for tests."""
    global _community_messaging_service
    _community_messaging_service = None

