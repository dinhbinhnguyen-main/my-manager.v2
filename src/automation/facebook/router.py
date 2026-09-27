"""Unified Facebook Action Router for my-manager.v2."""

import logging
from typing import Dict, Any, List, Optional

from src.core.models import Account
from src.automation.base_automator import BaseAutomator
from src.automation.facebook.login import FBLoginAction
from src.automation.facebook.warmup import FBWarmupAction
from src.automation.facebook.marketplace import FBMarketplaceAction
from src.automation.facebook.actions.post_group import FBPostGroupAction
from src.automation.facebook.actions.join_group import FBJoinGroupAction
from src.automation.facebook.actions.list_group_share import FBGroupShareAction
from src.automation.facebook.actions.scroll_feed import FBScrollFeedAction

logger = logging.getLogger(__name__)


class FBActionRouter:
    """Dispatches requested Facebook actions to their respective handlers."""

    @staticmethod
    def dispatch(
        automator: BaseAutomator,
        account: Account,
        action_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> bool:
        params = params or {}
        action = action_name.lower().strip()
        logger.info(f"Routing Facebook action '{action}' for account UID {account.uid}...")

        if action in ["login", "fb_login"]:
            act = FBLoginAction(automator, account)
            return act.execute()

        elif action in ["warmup", "scroll", "scroll_feed", "fb_scroll_feed"]:
            act = FBScrollFeedAction(automator, account)
            return act.execute(
                max_swipes=params.get("max_swipes", params.get("scroll_count", 20)),
                min_delay=params.get("min_delay", 3.0),
                max_delay=params.get("max_delay", 8.0),
                max_likes=params.get("max_likes", 3)
            )

        elif action in ["marketplace", "marketplace_post", "fb_marketplace"]:
            act = FBMarketplaceAction(automator, account)
            return act.execute_v1_real_estate_post(
                transaction_type=params.get("transaction_type", "sale"),
                use_ai=params.get("use_ai", True)
            )

        elif action in ["post_group", "fb_post_group"]:
            group_id = params.get("group_id")
            if not group_id:
                logger.error("Missing required parameter 'group_id' for post_group action.")
                return False

            content = params.get("content", "Bài viết chia sẻ bất động sản.")
            images = params.get("image_paths", [])
            act = FBPostGroupAction(automator, account)
            return act.execute(group_id=str(group_id), content=content, image_paths=images)

        elif action in ["join_group", "fb_join_group"]:
            group_id = params.get("group_id")
            if not group_id:
                logger.error("Missing required parameter 'group_id' for join_group action.")
                return False

            act = FBJoinGroupAction(automator, account)
            return act.execute(group_id=str(group_id))

        elif action in ["group_share", "list_group_share", "fb_list_group_share"]:
            group_ids = params.get("group_ids", [])
            if not group_ids and "group_id" in params:
                group_ids = [params["group_id"]]

            if not group_ids:
                logger.error("Missing required parameter 'group_ids' for group_share action.")
                return False

            share_groups_count = int(params.get("share_groups_count", params.get("max_share_groups", 20)))

            act = FBGroupShareAction(automator, account)
            return act.execute(
                group_ids=[str(g) for g in group_ids],
                use_v1_product=params.get("use_v1_product", True),
                use_ai=params.get("use_ai", True),
                share_groups_count=share_groups_count,
                custom_content=params.get("custom_content")
            )

        else:
            logger.error(f"Unsupported Facebook action '{action_name}'.")
            return False


def execute_action(action_name: str, adb_port: int, params: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level action execution dispatcher used by JobRunner."""
    from src.db.repository import AccountRepository

    account_uid = params.get("account_uid", "")
    account = AccountRepository.get_by_uid(account_uid)
    if not account:
        # Create a transient Account instance if not found in DB
        account = Account(uid=account_uid, password="", username="")

    automator = BaseAutomator(adb_port=adb_port)
    try:
        if not automator.initialize():
            return {"status": "failed", "message": f"Failed to initialize ADB/UIAutomator2 on port {adb_port}"}
        ok = FBActionRouter.dispatch(automator, account, action_name, params)
        if ok:
            return {"status": "success", "message": f"Action '{action_name}' completed successfully"}
        else:
            return {"status": "failed", "message": f"Action '{action_name}' returned failure"}
    except Exception as e:
        logger.exception(f"Exception executing action '{action_name}': {e}")
        return {"status": "failed", "message": str(e)}
    finally:
        automator.close()

