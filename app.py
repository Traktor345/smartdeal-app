import streamlit as st
import pandas as pd
import requests
import base64

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(
    page_title="eBay Smart Search",
    page_icon="🛍️",
    layout="wide"
)

# --- ЛОГИКА АГРЕГАТОРА (BACKEND) ---

class EbayAggregator:
    def __init__(self, api_keys):
        self.keys = api_keys
        self.target_currency = "USD"
        self.stop_words = {'купить', 'цена', 'поиск', 'лучший', 'buy', 'price', 'cheap', 'best', 'find'}
        self.rates = self._get_exchange_rates()

    @st.cache_data(ttl=3600)
    def _get_exchange_rates(_self):
        """Кеширование курсов валют"""
        if not _self.keys.get('exchange_rate_key'):
            return {}
        
        url = f"https://v6.exchangerate-api.com/v6/{_self.keys['exchange_rate_key']}/latest/{_self.target_currency}"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if data.get('result') == 'success':
                return data['conversion_rates']
        except Exception:
            return {}
        return {}

    def _convert_price(self, price, currency):
        """Конвертация цены в USD"""
        if currency == self.target_currency:
            return price
        if not self.rates or currency not in self.rates:
            return price 
        rate = self.rates.get(currency, 1)
        return price / rate

    def _nlp_clean_query(self, query):
        words = query.lower().split()
        keywords = [w for w in words if w not in self.stop_words]
        return " ".join(keywords)

    def _get_ebay_token(self):
        """Получение токена eBay (Client Credentials)"""
        try:
            if not self.keys['ebay_client_id'] or not self.keys['ebay_client_secret']:
                return None
            
            auth_str = f"{self.keys['ebay_client_id']}:{self.keys['ebay_client_secret']}"
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + base64.b64encode(auth_str.encode()).decode()
            }
            data = {
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope"
            }
            response = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data, timeout=10)
            response.raise_for_status()
            return response.json().get('access_token')
        except Exception as e:
            print(f"Auth Error: {e}")
            return None

    def search_ebay(self, query, condition="New"):
        """Поиск по eBay API"""
        clean_query = self._nlp_clean_query(query)
        token = self._get_ebay_token()
        
        if not token:
            return []

        # Формирование фильтров (IDs состояний товара)
        filter_str = ""
        if condition == "New":
            filter_str = "&filter=conditionIds:{1000}"
        elif condition == "Used/Refurbished":
            filter_str = "&filter=conditionIds:{1500|2000|2500|3000}"

        url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={clean_query}&limit=10{filter_str}"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            results = []
            
            if 'itemSummaries' in data:
                for item in data['itemSummaries']:
                    # Цена и валюта
                    price_obj = item.get('price', {})
                    raw_price = float(price_obj.get('value', 0))
                    currency = price_obj.get('currency', 'USD')
                    
                    # Доставка
                    shipping = 0.0
                    if 'shippingOptions' in item and len(item['shippingOptions']) > 0:
                        ship_opt = item['shippingOptions'][0]
                        ship_cost = ship_opt.get('shippingCost', {})
                        shipping = float(ship_cost.get('value', 0))

                    # Итоговая цена (Landed Cost)
                    final_price = self._convert_price(raw_price + shipping, currency)
                    
                    cond_text = item.get('condition', "Unknown")
                    image_url = item.get('image', {}).get('imageUrl', '')

                    results.append({
                        "Source": "eBay",
                        "Title": item.get('title'),
                        "Condition": cond_text,
                        "Price Info": f"{raw_price} {currency} (+ {shipping} ship)",
                        "Total (USD)": final_price,
                        "Image": image_url,
                        "URL": item.get('itemWebUrl')
                    })
            return results
        except Exception as e:
            st.error(f"Ошибка соединения с eBay: {e}")
            return []

    def get_mock_data(self, condition_filter):
        """Демонстрационные данные (если нет ключей)"""
        mock_db = [
            {"Source": "eBay", "Title": "Apple iPhone 15 Pro 128GB (New)", "Condition": "New", "Price Info": "999.00 USD (+ 0 ship)", "Total (USD)": 999.00, "Image": "https://i.ebayimg.com/images/g/test/s-l500.jpg", "URL": "#"},
            {"Source": "eBay", "Title": "Apple iPhone 15 Pro (Open Box)", "Condition": "Open Box", "Price Info": "850.00 USD (+ 15 ship)", "Total (USD)": 865.00, "Image": "https://i.ebayimg.com/images/g/test2/s-l500.jpg", "URL": "#"},
            {"Source": "eBay", "Title": "iPhone 15 Pro Parts Only", "Condition": "Parts", "Price Info": "200.00 USD (+ 10 ship)", "Total (USD)": 210.00, "Image": "https://i.ebayimg.com/images/g/test3/s-l500.jpg", "URL": "#"},
        ]
        
        if condition_filter == "New":
            return [x for x in mock_db if "New" in x['Condition']]
        elif condition_filter == "Used/Refurbished":
            return [x for x in mock_db if "New" not in x['Condition']]
        return mock_db

# --- ИНТЕРФЕЙС (UI) ---

def main():
    st.title("🛒 eBay Smart Search")
    st.caption("Быстрый поиск товаров с фильтрацией состояния и конвертацией цен")

    with st.sidebar:
        st.header("Настройки")
        
        condition = st.radio(
            "Состояние:",
            ("New", "Used/Refurbished", "Any"),
            index=0
        )
        
        st.divider()
        
        use_mock = st.checkbox("Демо-режим", value=True)
        
        with st.expander("API Ключи (eBay)"):
            ebay_id = st.text_input("Client ID", type="password")
            ebay_secret = st.text_input("Client Secret", type="password")
            ex_rate_key = st.text_input("ExchangeRate API (Optional)", type="password")

    query = st.text_input("Поиск товара:", placeholder="Например: Sony PlayStation 5 Slim")
    
    if st.button("Найти", type="primary"):
        if not query:
            st.warning("Введите запрос!")
            return

        api_keys = {
            'ebay_client_id': ebay_id,
            'ebay_client_secret': ebay_secret,
            'exchange_rate_key': ex_rate_key
        }

        app = EbayAggregator(api_keys)

        with st.spinner('Поиск на eBay...'):
            if use_mock:
                # Имитация
                import time
                time.sleep(0.5)
                results = app.get_mock_data(condition)
            else:
                results = app.search_ebay(query, condition)

        if results:
            df = pd.DataFrame(results)
            df = df.sort_values(by="Total (USD)")

            # Метрики
            if not df.empty:
                best = df.iloc[0]
                c1, c2 = st.columns(2)
                c1.metric("Лучшая цена", f"${best['Total (USD)']:.2f}")
                c2.metric("Найдено", len(df))

                st.data_editor(
                    df,
                    column_config={
                        "Image": st.column_config.ImageColumn("Фото", width="small"),
                        "URL": st.column_config.LinkColumn("Ссылка", display_text="Купить"),
                        "Total (USD)": st.column_config.NumberColumn("Итого", format="$%.2f"),
                        "Price Info": st.column_config.TextColumn("Цена + Доставка"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=600
                )
        else:
            st.info("Ничего не найдено. Проверьте ключи или измените запрос.")

if __name__ == "__main__":
    main()
