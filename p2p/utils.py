import random
from datetime import timedelta, datetime

def simulate_intraday_prices(price_start, price_end, steps=50):
    prices = [float(price_start)]
    for i in range(steps - 2):
        avg = float(price_start) + (float(price_end) - float(price_start)) * (i + 1) / (steps - 1)
        noise = random.uniform(-0.4, 0.4)
        prices.append(round(avg + noise, 2))
    prices.append(float(price_end))
    return prices

def build_fake_chart(history):
    chart_points = []
    for i in range(len(history) - 1):
        d0, p0 = history[i]
        d1, p1 = history[i+1]
        steps = 50
        # равномерное время между двумя датами
        total_seconds = (datetime.combine(d1, datetime.min.time()) - datetime.combine(d0, datetime.min.time())).total_seconds()
        intraday = simulate_intraday_prices(p0, p1, steps)
        for j in range(steps):
            t = datetime.combine(d0, datetime.min.time()) + timedelta(seconds=total_seconds * j // steps)
            chart_points.append((t, intraday[j]))
    chart_points.append((datetime.combine(history[-1][0], datetime.min.time()), float(history[-1][1])))
    return chart_points
