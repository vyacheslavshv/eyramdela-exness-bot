from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "users" ADD "pending_since" TIMESTAMP;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "users" DROP COLUMN "pending_since";"""


MODELS_STATE = (
    "eJztmllv2zgQgP8K4acsNglS2Tl235xj2yziZJG6u0WLQqBFWiYskSpJ5UCR/74kJVm3an"
    "t9YvVmc2Yo8huSMzx+dHyGsCeO+yEi8o65nd/Bjw6FPlY/SrJD0IFBkEp0gYQjzyhDrWV7"
    "sdpISA4dqQRj6AmsihAWDieBJIxq9X4QYIqOGPVegZBQ4iNlQAXRcqBqAWPGAcKj0HUJdc"
    "GvACKfUECoCLCjlY71dxBz1IeUwuqqDCn5HmJbMhfLCeaq4q/fVDGhCL9gkfwNpvaYYA/l"
    "eBGkKzDltnwNTNktlX8YRd3ake0wL/Rpqhy8ygmjM21CpS51McVcdUBXL3mo8dHQ82LUCd"
    "GopalK1MSMDcJjGHraCdq65IOkMMMwLnIY1f5TrRGmg67+ypH1rnfeu+ie9S6UimnJrOT8"
    "Lepe2vfI0BC4H3bejBxKGGkYjCk3iT3scujbVQAviVvLsGD4c5gJuiaaScG6cf5mWd3uuX"
    "XSPbs47Z2fn16czLiWRU2AL2/fa8ZKgak5F83GBHoKGT/hiEce79UE8mq4M4MCVtWV3cTq"
    "wxfbw9SVE/X3rNdA7O/+49WH/uPBWe+XPLb7WGIZUR4gwhISr0xwiF9qhmdqsRTCmE8DwX"
    "RtXQ3CBmTDm89miPlCfPeyqA4G/c+Gov8aS+4e7t8n6hm0V3cPlwWkDse6+zasGJjXSiKJ"
    "j6vR5i0LeFFsepz82M3xqrqAHlSwiqtugn87uPk47A/+ynnguj+80RIrRz8pPTgrjO1ZJe"
    "Cf2+EHoP+CLw/3NwYgE9Ll5oup3vBLR7cJhpLZlD3bEGUoJKUJqTcdFcfTzPquC0bQmT5D"
    "juyShFmsTrcs8i2/WAIpdI1XNFzdzDhZecQefB1gIaBZZUvJTE7emNBwrWn7kaqYL6sZwE"
    "AAqBMN3ROMohTjSBCEQVwT0P0EkgGVXQDGicpFoNT5SCgwLyc1K6mxzWk2ntPMHGb7wl04"
    "samybrObhuxGD3V76TyyynpduFcds7fDe78i98qZt6F7DaH7kzChqRSyTXljqNbzd84I3Q"
    "fDeJ6b8KhiJpRgAgVQvsXaVIXYZyInJpiOmKw4ZlimhjYC/89PFTZEcwth1/wuAa4/V8ja"
    "7Mm+OH+0YJ2eznG2oLRqDxeMLE9yTLiQ9qIs81YtzYRmoDgsBHJmsJcMu9YcCLtWLUEtKp"
    "wWvlC1ubTDqrWz4cgwZ7USlGtfN3Mg352czEFSadWiNLI8S30XEYpFOKYWGzt77TA6YiqF"
    "06xWNrXnOYO16s9grdIZrALDl9t25C3bbccObDuyjn3CnKh+LOPZgukKXLtbB+875Mmk24"
    "2u9KBKSZwJdqZLOLNk3LpzF9ypNvdUdXhZh+bNW5du2aVT4kyXWmpzhq0bt+xG/dpFzypB"
    "qFOx2Wl2Zcm4decuLLSORzCV9uJbhmrrvdzNWvPswaz6LZhV2oEZOAFn2l3CHnvQrWBb/4"
    "6jxnxP4G76UYehhbCaHkTakklY8WbmGjvEh14D7lIFxfUpquE4rmnfyF/fXN0O+ncH73qH"
    "0bGMwkwkzo7wXvUwVvUjvGwiljVuF/wtL/i6a9gJJXlSLgmIjTlnvGJhqr2oqK9gc5fXJ/"
    "9h1V/BBdCOXF32MSfOpFP1eDqSHDY+nU51fnZ/WQ+3vWHc+A3jE+ZCN2mBNC1jsq6j3T28"
    "rtFTYwGIsfp+AlzLFYP6oqx83v3nx4f72uAhqx94f6Kqg18RceQh8IiQ33YTawNF3evmvL"
    "aYwhbCu67gctvh5e1fN26CtQ=="
)
