huff_n_puff_high_rise = {
    "name": "HuffNPuffHighRise",
    "simulator" : {
        "host": "127.0.0.1",
        "port": 9090,
        "roi" : {
            "cash_meter": [0.191667, 0.791779, 0.808333, 0.820443],
            "reels": [0.218519, 0.604651, 0.780556, 0.766901],
            "cyclic_message": [],
            "cyclic_message_2": []
        },
        "logs" : "C:\\logs\\Game\\HuffNPuffHighRise\\Logs\\HuffNPuffHighRise_Client.log",
        "game_config" : "C:\\re\\games\\HuffNPuffHighRise\\GameConfig",
        "win_geometry" : "C:\\re\\games\\HuffNPuffHighRise\\GameConfig\\winGeometry.xml"
        },
    "egm" : {
        "host": "10.2.168.252",
        "port": 9090,
        "roi" : {
            "cash_meter": [0.000000, 0.956044, 1.000000, 1.000000],
            "reels": [0.043544, 0.663567, 0.954955, 0.917160],
            "cyclic_message": [],
            "cyclic_message_2": []
        },
        "logs" :  "\\\\10.2.255.20\\c$\\wms_games\\Logs\\Game\\HuffNPuffHighRise\\Logs\\HuffNPuffHighRise_Client.log",
        "game_config" : "\\\\10.2.255.20\\c$\\games\\HuffNPuffHighRise\\games\\3093998_HuffNPuffHighRise\\GameConfig",
        "win_geometry" : "\\\\10.2.255.20\\c$\\games\\HuffNPuffHighRise\\games\\3093998_HuffNPuffHighRise\\GameConfig\\winGeometry.xml",
    },
    "symbols": {
    },
    "scatter_symbols": [],
    "meter": {
        "band": []
    },

    "reel_bounds": {
        "rows": 3,
        "columns": 5,
        "inset": 0.04
    },
    "wild_card_replacement": [
    ],
    "gaf": {
        "game_type": "BallyStyle",
        "gdk_version": "12",
        "object_query_root": "app/games/HuffNPuffHighRise/ObjectQuery.json",
        "actions": [
            "take_win", "toggle_credit_meter"
        ],
    }
}