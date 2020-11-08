import click
import httpx

import broker as br


@click.group()
def cli():
    pass


@cli.group()
def position():
    click.echo('position')

 
@position.command()
def list():

    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    positions = broker.positions
    
    for pos in positions:
        click.echo(pos)


if __name__ == '__main__':
    cli()
