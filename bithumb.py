import queue
import re
import requests
import datetime
import time
import bithumb_api
import threading
from bs4 import BeautifulSoup

def is_english(text):
    # 텍스트에 영어 알파벳 문자가 포함되어 있는지 확인
    for char in text:
        if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
            return True
    return False

def get_suspended_coins():
    url = "https://cafe.bithumb.com/view/boards/43?keyword=&noticeCategory=7"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return {}

    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.select("tr[style='cursor:pointer;border-top:1px solid #dee2e6;background-color: white']")


    suspended_coins = {}
    today = datetime.datetime.now().strftime("%H:%M")
    current_minute = datetime.datetime.now().strftime("%H:%M")  # 현재 시간의 분 단위
    for row in rows:
        title_elem = row.select_one(".one-line a")
        date_elem = row.select_one("td.small-size[style='vertical-align: middle']:not(.invisible-mobile)")
        event_number = row.get('onclick').split("'")[1] if row.get('onclick') else None

        if title_elem and "입출금 일시 중지" in title_elem.text:
            coin_data = title_elem.text.split()[1]
            coin_name, coin_symbol = coin_data.split("(") if "(" in coin_data else (coin_data, coin_data)
            coin_symbol = coin_symbol.rstrip(")")
            date = date_elem.text.strip() if date_elem else "Unknown Date"

            date = today
            if date == today and event_number:
                detail_url = f"https://cafe.bithumb.com/view/board-contents/{event_number}"
                detail_response = requests.get(detail_url, headers=headers)
                if detail_response.status_code == 200:
                    detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
                    writer_date_elem = detail_soup.select_one(".writer-name.date.col-12.col-md-4")

                    if writer_date_elem:
                        writer_date_raw = writer_date_elem.text.strip()
                        match = re.search(r"(\d{4}.\d{2}.\d{2} \d{2}:\d{2})", writer_date_raw)
                        writer_date = match.group(1) if match else "Unknown Writer Date"

                        # 현재 시간의 분 단위와 writer_date의 분 단위가 일치하는 경우만 추가
                        if writer_date.split()[-1] == "10:30":
                            if is_english(coin_symbol):
                                suspended_coins[coin_symbol] = {"date": date, "event_number": event_number,
                                                                "writer_date": writer_date}
    return suspended_coins


# ... 기존의 import문 ...

class BithumbTrader:
    def __init__(self, api):
        self.api = api
        self.owned_coins = {}  # 현재 보유하고 있는 코인 및 그 코인의 구매 가격을 저장하는 딕셔너리
        self.new_coins = queue.Queue()
        self.traded_flags = {}  # 각 코인에 대해 구매 및 판매가 이루어졌는지 추적하는 딕셔너리

    def buy_coin(self, coin_symbol, units):
        # 코인을 시장가로 구매하는 코드
        params = {
            "units": units,
            "order_currency": coin_symbol,
            "payment_currency": "KRW"
        }
        response = self.api.xcoinApiCall("/trade/market_buy", params)
        return response

    def sell_coin(self, coin_symbol, units):
        # 코인을 시장가로 판매하는 코드
        params = {
            "units": units,
            "order_currency": coin_symbol,
            "payment_currency": "KRW"
        }
        response = self.api.xcoinApiCall("/trade/market_sell", params)
        return response

    def check_price(self, coin_symbol):
        # 코인의 현재 가격을 조회하는 코드
        payment_currency = "KRW"
        params = {
            "order_currency": coin_symbol,
            "payment_currency": payment_currency,
            "count": 1
        }
        response = self.api.xcoinApiCall(f"/public/transaction_history/{coin_symbol}_{payment_currency}?count=1", params)
        current_price = float(response['data'][0]['price'])
        return current_price

def check_suspended_coins(trader):
    test_cash = 3000
    while True:
        suspended_coins = get_suspended_coins()
        for coin_symbol, coin_info in suspended_coins.items():
            if coin_symbol not in trader.owned_coins and not trader.traded_flags.get(coin_symbol, False):

                price = trader.check_price(coin_symbol)
                units_to_buy = test_cash / price
                formatted_units = "{:.4f}".format(units_to_buy)
                # 코인을 구매
                print(f"buying {coin_symbol} {formatted_units}")
                response = trader.buy_coin(coin_symbol, formatted_units)
                # 구매한 코인의 수량과 가격을 큐에 저장
                trader.new_coins.put({coin_symbol: {"price": price, "units": formatted_units}})
                # 플래그 설정
                trader.traded_flags[coin_symbol] = True

        time.sleep(1.5)  # 1초마다 조건 확인



def trade_logic(trader):
    test_cash = 3000
    while True:
        # 새로운 코인 정보가 큐에 있으면 가져와서 owned_coins에 추가
        while not trader.new_coins.empty():
            new_coin_data = trader.new_coins.get()
            for coin_symbol, coin_info in new_coin_data.items():
                trader.owned_coins[coin_symbol] = coin_info["price"]

        for coin_symbol in list(trader.owned_coins.keys()):
            current_price = trader.check_price(coin_symbol)
            buy_price = trader.owned_coins[coin_symbol]

            if current_price >= buy_price * 1.025 or current_price <= buy_price * 0.99:
                # 보유한 코인의 수량으로 판매
                units_to_sell = new_coin_data[coin_symbol]["units"]
                print(f"selling {buy_price} to {coin_symbol} {units_to_sell}")
                response = trader.sell_coin(coin_symbol, units_to_sell)

                # 판매 후 owned_coins 딕셔너리에서 해당 코인 정보 제거 및 플래그 초기화
                del trader.owned_coins[coin_symbol]
                trader.traded_flags[coin_symbol] = False

        time.sleep(1.5)  # 0.5초마다 조건 확인

def main():
    api = bithumb_api.XCoinAPI("8beb19f57de6f9cdea23d7f53b6677c7", "35b6253e51a45957037cb566cab944bb")
    trader = BithumbTrader(api)

    trader.check_price('BTC')

    t1 = threading.Thread(target=check_suspended_coins, args=(trader,))
    t2 = threading.Thread(target=trade_logic, args=(trader,))

    t1.start()
    t2.start()

    t1.join()
    t2.join()

if __name__ == "__main__":
    # main()
    print("started")
    main()
