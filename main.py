import click
import httpx


@click.group()
def cli():
    pass


@cli.group()
def position():
    click.echo('position')
    
    
@position.command()
def enter():
    click.echo('entering position')
    

@position.command()
def exit():
    click.echo('exiting position')


@position.command()
def list():
    
    httpx.get('https://tradie')


if __name__ == '__main__':
    cli()
