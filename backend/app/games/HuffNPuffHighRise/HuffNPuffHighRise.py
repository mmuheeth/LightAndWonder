huff_n_puff_high_rise = {
    "name": "HuffNPuffHighRise",
    "log": r"\\10.2.168.252\c$\wms_games\Logs\Game\FortuneOx\Logs\FortuneOx_Client.log",
    "game_config": r"\\10.2.168.252\c$\games\FortuneOx\games\FortuneOx\GameConfig",
    "win_geometry": r"\\10.2.168.252\c$\games\FortuneOx\games\FortuneOx\GameConfig\winGeometry.xml",
    "symbols": {},
    "scatter_symbols": ["SC", "FG", "SF"],
    "meter": {
        "band": [0.138889, 0.555556]
    },
    "roi": {
        "simulator": {
            "cash_meter": [0.0, 0.844468, 1.0, 0.884554],
            "cyclic_message": [0.0, 0.8475, 0.18, 0.8568],
            "cyclic_message_2": [0.0, 0.8568, 0.18, 0.867],
            "reels": [0.045131, 0.559722, 0.95487, 0.822222]
        },
        "egm": {
            "cash_meter": [0.241146, 0.866667, 0.757813, 1.0],
            "reels": [0.055208, 0.094444, 0.936979, 0.813889],
            "cyclic_message": [0.015625, 0.882407, 0.104167, 0.909259],
            "cyclic_message_2": [0.015625, 0.912963, 0.072917, 0.935185]
        }
    },
    "reel_bounds": {
        "rows": 3,
        "columns": 5,
        "inset": [0.055, 0.0]
    },
    "wild_card_replacement": [],
    "gaf": {
        "host": {
            "simulator": "127.0.0.1",
            "egm": "10.2.168.252"
        },
        "port": {
            "simulator": 9090,
            "egm": 9090
        },
        "game_type": "BallyStyle",
        "gdk_version": "12",
        "object_query_root": "app/config/game_config/gaf_objects/FortuneOxEGM",
    }
}