from textwrap import dedent
from typing import Dict, Any

from bot.utils import translate_alert_type


class AlertManager:
    @staticmethod
    def format_alert_details(alert_data: Dict[str, Any]) -> str:
        return dedent(
            f"""
            جفت ارز: #{alert_data.get('pair', 'N/A')}
            نوع: {translate_alert_type(alert_data.get('alert_type', 'N/A'))}
            قیمت: {alert_data.get('price', 'N/A')}
            متن: {alert_data.get('alert_description', 'بدون متن')}
        """
        )

    @staticmethod
    def format_trigger_message(
        alert_data: Dict, trigger_reason: str, current_price: float, trigger_count: int
    ) -> str:
        return dedent(
            f"""
            🔔 آلارم فعال شد! 🔔

            {trigger_reason}

            جفت ارز: #{alert_data['pair']}
            قیمت هدف: {alert_data['price']}
            قیمت فعلی: {current_price}
            متن: {alert_data['alert_description']}

            🔄 تعداد تکرار: {trigger_count}
        """
        )
