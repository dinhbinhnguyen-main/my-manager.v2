"""Unit tests for FBReelInteractionsAction and action router integration."""

import unittest
from unittest.mock import MagicMock, patch

from src.core.models import Account, AccountStatus
from src.automation.facebook.actions.reel_interactions import FBReelInteractionsAction
from src.automation.facebook.router import FBActionRouter
from src.db.database import init_db


class TestReelInteractions(unittest.TestCase):
    def setUp(self):
        init_db()
        self.mock_automator = MagicMock()
        self.mock_device = MagicMock()
        self.mock_automator.device = self.mock_device
        self.mock_account = Account(uid="61588749472767", username="test_user", password="pwd")

    def test_open_reel_deeplink(self):
        """Ensures open_reel formats deeplink with IntentUriHandler to avoid ResolverActivity."""
        action = FBReelInteractionsAction(self.mock_automator, self.mock_account)
        action.open_reel("3046151639050612")

        expected_cmd = (
            'am start -a android.intent.action.VIEW '
            '-d "https://www.facebook.com/reel/3046151639050612" '
            '-n com.facebook.katana/com.facebook.katana.IntentUriHandler'
        )
        self.mock_device.shell.assert_called_with(expected_cmd)

    def test_like_skipped_when_already_liked(self):
        """Ensures like step is skipped if reel is already liked (selected=True)."""
        action = FBReelInteractionsAction(self.mock_automator, self.mock_account)
        # Mock device selector with selected=True
        self.mock_device.return_value.exists = True

        with patch.object(action, "open_reel", return_value=True), \
             patch("time.sleep"):
            # Set selected=True on the selector
            self.mock_device.return_value.info = {"selected": True}
            result = action.handle_like()
            self.assertTrue(result)
            # Click should not be called on like button because it was already liked
            self.mock_device.return_value.click.assert_not_called()

    def test_save_clicks_and_presses_back(self):
        """Ensures save clicks Save button and presses back to return to main reel screen."""
        action = FBReelInteractionsAction(self.mock_automator, self.mock_account)

        # Mock save button exists and not already saved
        def mock_selector(**kwargs):
            mock_elem = MagicMock()
            if kwargs.get("description") == "Saved":
                mock_elem.exists = False
            elif kwargs.get("description") == "Save":
                mock_elem.exists = True
                mock_elem.info = {"bounds": {"left": 954, "top": 1418}}
            else:
                mock_elem.exists = False
            return mock_elem

        self.mock_device.side_effect = mock_selector

        result = action.handle_save()
        self.assertTrue(result)
        # Verify press back was called
        self.mock_device.press.assert_called_with("back")

    def test_comment_posts_and_presses_back(self):
        """Ensures comment types text, clicks send, and presses back to return to main reel."""
        action = FBReelInteractionsAction(self.mock_automator, self.mock_account)

        mock_input = MagicMock()
        mock_input.exists = True
        mock_send = MagicMock()
        mock_send.exists = True
        mock_comment_btn = MagicMock()
        mock_comment_btn.exists = True

        def mock_selector(**kwargs):
            if "comment" in str(kwargs).lower() and "auto" not in str(kwargs).lower():
                return mock_comment_btn
            if kwargs.get("className") == "android.widget.AutoCompleteTextView":
                return mock_input
            if kwargs.get("description") == "Send":
                return mock_send
            elem = MagicMock()
            elem.exists = False
            return elem

        self.mock_device.side_effect = mock_selector

        result = action.handle_comment("Video tuyệt vời!")
        self.assertTrue(result)
        mock_input.set_text.assert_called_with("Video tuyệt vời!")
        mock_send.click.assert_called()
        self.mock_device.press.assert_called_with("back")

    def test_comment_random_fallback_when_empty(self):
        """Ensures that when comment_content is empty, a random preset comment is chosen and posted."""
        action = FBReelInteractionsAction(self.mock_automator, self.mock_account)

        mock_input = MagicMock()
        mock_input.exists = True
        mock_send = MagicMock()
        mock_send.exists = True
        mock_comment_btn = MagicMock()
        mock_comment_btn.exists = True

        def mock_selector(**kwargs):
            if "comment" in str(kwargs).lower() and "auto" not in str(kwargs).lower():
                return mock_comment_btn
            if kwargs.get("className") == "android.widget.AutoCompleteTextView":
                return mock_input
            if kwargs.get("description") == "Send":
                return mock_send
            elem = MagicMock()
            elem.exists = False
            return elem

        self.mock_device.side_effect = mock_selector

        result = action.handle_comment("")
        self.assertTrue(result)
        # Check that set_text was called with a non-empty string from DEFAULT_REEL_COMMENTS
        from src.automation.facebook.actions.reel_interactions import DEFAULT_REEL_COMMENTS
        args, _ = mock_input.set_text.call_args
        self.assertIn(args[0], DEFAULT_REEL_COMMENTS)

    def test_share_selects_groups_and_posts(self):
        """Ensures share navigates through Group selection, clicks Next and Post."""
        action = FBReelInteractionsAction(self.mock_automator, self.mock_account)

        mock_share_btn = MagicMock()
        mock_share_btn.exists = True
        mock_group_opt = MagicMock()
        mock_group_opt.exists = True
        mock_cb = MagicMock()
        mock_cb.exists = True
        mock_cb.info = {"contentDescription": "Nhóm BĐS Đà Lạt"}
        mock_next = MagicMock()
        mock_next.exists = True
        mock_post = MagicMock()
        mock_post.exists = True

        def mock_selector(**kwargs):
            if kwargs.get("description") == "Group":
                return mock_group_opt
            if kwargs.get("className") == "android.widget.CompoundButton":
                return [mock_cb]
            if kwargs.get("description") == "Next":
                return mock_next
            if kwargs.get("description") == "Post":
                return mock_post
            elem = MagicMock()
            elem.exists = True
            return elem

        self.mock_device.side_effect = mock_selector

        result = action.handle_share_to_groups(share_num=1)
        self.assertTrue(result)
        mock_group_opt.click.assert_called()
        mock_cb.click.assert_called()
        mock_next.click.assert_called()
        mock_post.click.assert_called()

    def test_share_random_group_selection(self):
        """Ensures that reel sharing selects groups randomly from available groups without keyword/transaction restrictions."""
        account = Account(uid="61588749472767", username="test_user", password="pwd")
        action = FBReelInteractionsAction(self.mock_automator, account)

        mock_share_btn = MagicMock()
        mock_share_btn.exists = True
        mock_group_opt = MagicMock()
        mock_group_opt.exists = True

        mock_cb_1 = MagicMock()
        mock_cb_1.exists = True
        mock_cb_1.info = {"contentDescription": "Nhóm Bất Động Sản Đà Lạt"}

        mock_cb_2 = MagicMock()
        mock_cb_2.exists = True
        mock_cb_2.info = {"contentDescription": "Hội Yêu Thích Đà Lạt"}

        mock_next = MagicMock()
        mock_next.exists = True
        mock_post = MagicMock()
        mock_post.exists = True

        def mock_selector(**kwargs):
            if kwargs.get("description") == "Group":
                return mock_group_opt
            if kwargs.get("className") == "android.widget.CompoundButton":
                return [mock_cb_1, mock_cb_2]
            if kwargs.get("description") == "Next":
                return mock_next
            if kwargs.get("description") == "Post":
                return mock_post
            elem = MagicMock()
            elem.exists = True
            return elem

        self.mock_device.side_effect = mock_selector

        result = action.handle_share_to_groups(share_num=1)
        self.assertTrue(result)
        # Exactly one of the groups should be clicked randomly
        clicked_count = mock_cb_1.click.call_count + mock_cb_2.click.call_count
        self.assertEqual(clicked_count, 1)
        mock_next.click.assert_called()
        mock_post.click.assert_called()

    def test_share_single_select_button_flow(self):
        """Ensures Flow 2 (03_group_clicked_02) clicks group button directly, posts on composer, and repeats for share_num > 1."""
        account = Account(uid="61588749472767", username="test_user", password="pwd")
        action = FBReelInteractionsAction(self.mock_automator, account)

        mock_share_btn = MagicMock()
        mock_share_btn.exists = True
        mock_group_opt = MagicMock()
        mock_group_opt.exists = True

        mock_group_btn_1 = MagicMock()
        mock_group_btn_1.exists = True
        mock_group_btn_1.info = {
            "contentDescription": "MUA BÁN NHÀ ĐẤT ĐÀ LẠT ✅",
            "bounds": {"left": 0, "top": 636, "right": 1080, "bottom": 783}
        }

        mock_group_btn_2 = MagicMock()
        mock_group_btn_2.exists = True
        mock_group_btn_2.info = {
            "contentDescription": "Nhà đất Đà Lạt",
            "bounds": {"left": 0, "top": 930, "right": 1080, "bottom": 1077}
        }

        mock_back_btn = MagicMock()
        mock_back_btn.exists = True

        mock_post = MagicMock()
        mock_post.exists = True

        def mock_selector(**kwargs):
            if kwargs.get("description") == "Group":
                return mock_group_opt
            if kwargs.get("className") in ("android.widget.CompoundButton", "android.widget.CheckBox", "android.widget.RadioButton"):
                return []
            if kwargs.get("className") == "android.widget.Button" and kwargs.get("clickable") is True:
                return [mock_group_btn_1, mock_group_btn_2]
            if kwargs.get("description") == "Back Button":
                return mock_back_btn
            if kwargs.get("description") == "Post":
                return mock_post
            elem = MagicMock()
            elem.exists = True
            return elem

        self.mock_device.side_effect = mock_selector

        result = action.handle_share_to_groups(share_num=2)
        self.assertTrue(result)
        # Both group buttons should be clicked across 2 rounds
        self.assertEqual(mock_group_btn_1.click.call_count, 1)
        self.assertEqual(mock_group_btn_2.click.call_count, 1)
        # Post was clicked twice
        self.assertEqual(mock_post.click.call_count, 2)
        # Back Button was clicked to exit Select group screen
        mock_back_btn.click.assert_called()

    def test_router_dispatch_reel_interactions(self):
        """Ensures FBActionRouter dispatches reel_interactions with proper params."""
        params = {
            "reel_id": "3046151639050612",
            "like": True,
            "comment": True,
            "comment_content": "Hay quá!",
            "share": True,
            "share_num": 1,
            "save": True,
            "watch_delay": 0.1,
        }

        with patch("src.automation.facebook.actions.reel_interactions.FBReelInteractionsAction.execute", return_value=True) as mock_exec:
            res = FBActionRouter.dispatch(self.mock_automator, self.mock_account, "reel_interactions", params)
            self.assertTrue(res)
            mock_exec.assert_called_once_with(
                reel_id="3046151639050612",
                like=True,
                comment=True,
                comment_content="Hay quá!",
                share=True,
                share_num=1,
                save=True,
                watch_delay=0.1,
            )


if __name__ == "__main__":
    unittest.main()
