from textwrap import dedent
from typing import Dict, Any

from bot.utils import translate_alert_type


class AlertManager:
    @staticmethod
    def format_alert_details(alert_data: Dict[str, Any]) -> str:
        alert_type = alert_data.get("alert_type")
        if alert_type == "alert_rsi":
            condition_text = (
                "بالاتر از"
                if alert_data.get("rsi_condition") == "above"
                else "پایین تر از"
            )
            return dedent(
                f"""
                جفت ارز: #{alert_data.get('pair', 'N/A')}
                نوع: {translate_alert_type(alert_type)}
                تایم فریم: {alert_data.get('timeframe', 'N/A')}
                دوره RSI: {alert_data.get('rsi_period', 'N/A')}
                شرط: RSI {condition_text} {alert_data.get('price')}
                متن: {alert_data.get('alert_description', 'بدون متن')}
                """
            )
        else:  # Default to price alert format
            return dedent(
                f"""
                جفت ارز: #{alert_data.get('pair', 'N/A')}
                نوع: {translate_alert_type(alert_type)}
                قیمت: {alert_data.get('price', 'N/A')}
                متن: {alert_data.get('alert_description', 'بدون متن')}
                """
            )

    @staticmethod
    def format_trigger_message(
        alert_data: Dict, trigger_reason: str, current_value: float, trigger_count: int
    ) -> str:
        alert_type = alert_data.get("alert_type")
        if alert_type == "alert_rsi":
            pair = alert_data.get("pair")
            timeframe = alert_data.get("timeframe")
            description = alert_data.get("alert_description")
            return dedent(
                f"""
                🔔 آلارم RSI فعال شد! 🔔

                {trigger_reason}

                جفت ارز: #{pair}
                تایم فریم: {timeframe}
                RSI فعلی: {current_value:.2f}
                متن: {description}

                🔄 تعداد تکرار: {trigger_count}
                """
            )
        else:  # Default to price alert format
            pair = alert_data.get("pair")
            target_price = alert_data.get("price")
            description = alert_data.get("alert_description")
            return dedent(
                f"""
                🔔 آلارم قیمت فعال شد! 🔔

                {trigger_reason}

                جفت ارز: #{pair}
                قیمت هدف: {target_price}
                قیمت فعلی: {current_value}
                متن: {description}

                🔄 تعداد تکرار: {trigger_count}
                """
            )
