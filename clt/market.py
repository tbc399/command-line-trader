import click


@click.group()
async def market():
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    market_days = await broker.calendar()

