import streamlit as st
import pandas as pd
import requests
import base64
from amazon.paapi import AmazonAPI

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="SmartDeal Aggregator", page_icon="⚖️", layout="wide")

# --- ЛОГИКА АГРЕГАТОРА (BACKEND) ---

class EcommerceAggregator:
    def __init__(self, api_keys):
        self.keys = api_keys
        self.stop_words = {'купить', 'цена', 'поиск', 'лучший', 'buy', 'price', 'cheap', 'best', 'find'}
        self.target_currency = "USD" 
        self.rates = self._get_exchange_rates()

    @st.cache_data(ttl=3600)
    def _get_exchange_rates(_self):
        """Получает актуальные курсы валют"""
        if not _self.keys.get('exchange_rate_key'):
            return {}
        url = f"https://v6.exchangerate-api.com/v6/{_self.keys['exchange_rate_key']}/latest/{_self.target_currency}"
        try:
            response = requests.get(url)
            data = response.json()
            return data.get('conversion_rates', {}) if data.get('result') == 'success' else {}
        except Exception:
            return {}

    def _convert_price(self, price, currency):
        """Конвертирует цену в USD"""
        if currency == self.target_currency: return price
        if not self.rates or currency not in self.rates: return price 
        rate = self.rates.get(currency, 1)
        return price / rate

    def _nlp_clean_query(self, query):
        words = query.lower().split()
        keywords = [w for w in words if w not in self.stop_words]
        return " ".join(keywords)

    def _get_ebay_token(self):
        try:
            if not self.keys['ebay_client_id'] or not self.keys['ebay_client_secret']: return None
            auth_str = f"{self.keys['ebay_client_id']}:{self.keys['ebay_client_secret']}"
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + base64.b64encode(auth_str.encode()).decode()
            }
            data = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
            response = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data)
            return response.json().get('access_token')
        except Exception:
            return None

    def search_ebay(self, query, condition="New"):
        """
        condition: 'New', 'Used', 'Any'
        eBay Condition IDs: 1000=New, 3000=Used, 1500=Open Box/Refurbished
        """
        clean_query = self._nlp_clean_query(query)
        token = self._get_ebay_token()
        if not token: return []

        # Формируем фильтр для API eBay
        filter_str = ""
        if condition == "New":
            filter_str = "&filter=conditionIds:{1000}"
        elif condition == "Used/Refurbished":
            filter_str = "&filter=conditionIds:{2000|2500|3000|4000|5000|6000}"
        # Если 'Any', фильтр не добавляем

        url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={clean_query}&limit=10{filter_str}"
        headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
        
        try:
            response = requests.get(url, headers=headers)
            data = response.json()
            results = []
            if 'itemSummaries' in data:
                for item in data['itemSummaries']:
                    raw_price = float(item['price']['value'])
                    currency = item['price']['currency']
                    
                    shipping = 0.0
                    if 'shippingOptions' in item and len(item['shippingOptions']) > 0:
                        ship_val = item['shippingOptions'][0].get('shippingCost', {'value': '0'})
                        shipping = float(ship_val.get('value', 0))

                    final_price = self._convert_price(raw_price + shipping, currency)
                    
                    # Получаем состояние текстом
                    cond_text = item.get('condition', "Unknown")

                    results.append({
                        "Source": "eBay",
                        "Title": item.get('title'),
                        "Condition": cond_text,
                        "Original Price": f"{raw_price} {currency}",
                        "Total (USD)": final_price,
                        "Image": item.get('image', {}).get('imageUrl', ''),
                        "URL": item.get('itemWebUrl')
                    })
            return results
        except Exception:
            return []

    def search_amazon(self, query):
        # Amazon по умолчанию ищет новые товары, если не указано иное.
        if not self.keys['amazon_access_key']: return []
        clean_query = self._nlp_clean_query(query)
        try:
            amazon = AmazonAPI(self.keys['amazon_access_key'], self.keys['amazon_secret_key'], self.keys['amazon_tag'], "US")
            products = amazon.search_items(keywords=clean_query)
            results = []
            for item in products['data']:
                price = item.prices.price.value if item.prices else 0
                results.append({
                    "Source": "Amazon",
                    "Title": item.item_info.title.display_value,
                    "Condition": "New", # Считаем по умолчанию новые
                    "Original Price": f"{price} USD",
                    "Total (USD)": price,
                    "Image": item.images.primary.large.url,
                    "URL": item.detail_page_url
                })
            return results
        except Exception:
            return []

    def get_mock_data(self, condition_filter):
        """Возвращает разные данные в зависимости от фильтра"""
        mock_db = [
            {"Source": "Amazon", "Title": "Sony WH-1000XM5 (New)", "Condition": "New", "Original Price": "348.00 USD", "Total (USD)": 348.00, "Image": "https://m.media-amazon.com/images/I/51SKmu2G9FL._AC_SL1000_.jpg", "URL": "#"},
            {"Source": "eBay", "Title": "Sony WH-1000XM5 (Open Box)", "Condition": "Open Box", "Original Price": "280.00 USD", "Total (USD)": 295.00, "Image": "https://i.ebayimg.com/images/g/test/s-l500.jpg", "URL": "#"},
            {"Source": "eBay", "Title": "Sony WH-1000XM5 (Used - Scratched)", "Condition": "Used", "Original Price": "150.00 USD", "Total (USD)": 165.00, "Image": "https://i.ebayimg.com/images/g/test2/s-l500.jpg", "URL": "#"},
        ]
        
        if condition_filter == "New":
            return [x for x in mock_db if x['Condition'] == "New"]
        elif condition_filter == "Used/Refurbished":
            return [x for x in mock_db if x['Condition'] != "New"]
        return mock_db

# --- ИНТЕРФЕЙС ---

def main():
    st.title("⚖️ SmartDeal: Честный поиск")
    
    with st.sidebar:
        st.header("Настройки поиска")
        # --- ФИЛЬТР СОСТОЯНИЯ ---
        condition_filter = st.radio(
            "Состояние товара:",
            ("New", "Used/Refurbished", "Any"),
            index=0,
            help="Выбирайте 'New' для корректного сравнения цен на новую технику"
        )
        st.divider()

        st.header("🔑 API Keys")
        use_mock = st.checkbox("Режим Demo", value=True)
        with st.expander("Ввести ключи"):
            ebay_id = st.text_input("eBay Client ID", type="password")
            ebay_secret = st.text_input("eBay Secret", type="password")
            amz_key = st.text_input("Amazon Access Key", type="password")
            amz_secret = st.text_input("Amazon Secret", type="password")
            amz_tag = st.text_input("Amazon Tag", type="password")
            ex_rate_key = st.text_input("ExchangeRate-API Key", type="password")

    query = st.text_input("Поиск товара:", placeholder="Например: DJI Mini 4 Pro")

    if st.button("Найти", type="primary"):
        if not query:
            st.warning("Введите запрос.")
            return

        api_keys = {
            'ebay_client_id': ebay_id, 'ebay_client_secret': ebay_secret,
            'amazon_access_key': amz_key, 'amazon_secret_key': amz_secret, 'amazon_tag': amz_tag,
            'exchange_rate_key': ex_rate_key
        }

        aggregator = EcommerceAggregator(api_keys)
        
        with st.spinner(f'Ищем {condition_filter.lower()} товары...'):
            if use_mock:
                import time
                time.sleep(0.5)
                results = aggregator.get_mock_data(condition_filter)
            else:
                # Передаем фильтр в поиск eBay
                ebay = aggregator.search_ebay(query, condition=condition_filter)
                
                # Если ищем только Б/У, Amazon можно пропустить (или искать Amazon Renewed, но это сложнее)
                amz = []
                if condition_filter in ["New", "Any"]:
                    amz = aggregator.search_amazon(query)
                
                results = ebay + amz

        if results:
            df = pd.DataFrame(results)
            df = df.sort_values(by="Total (USD)")
            
            # Статистика
            min_price = df['Total (USD)'].min()
            avg_price = df['Total (USD)'].mean()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Минимальная цена", f"${min_price:.2f}")
            c2.metric("Средняя цена", f"${avg_price:.0f}")
            c3.metric("Тип товаров", condition_filter)

            # Таблица с новым столбцом Condition
            st.data_editor(
                df,
                column_config={
                    "Image": st.column_config.ImageColumn("Фото", width="small"),
                    "URL": st.column_config.LinkColumn("Ссылка"),
                    "Condition": st.column_config.TextColumn("Состояние"),
                    "Total (USD)": st.column_config.NumberColumn("Итого (USD)", format="$%.2f"),
                },
                hide_index=True,
                use_container_width=True,
                height=600
            )
        else:
            st.warning(f"Товаров с состоянием '{condition_filter}' не найдено.")

if __name__ == "__main__":
    main()
