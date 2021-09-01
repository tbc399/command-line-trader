import click

from clt import broker as br

from clt import (
    config,
    context,
    account,
    position,
    market,
    watch,
    chart
)

from clt.utils import load_and_spin


'''
command ideas

context: different contexts to allow for multiple workspaces for various configurations
    clt context new <name>  # create a new context with the given name
    clt context <name>  # switch to the specified context
    clt context  # print the current context
    clt context list  # show all available contexts
    clt context rename <new-name>

config: configuration for the application as a whole and certain contexts
    clt config <command_name> [options]

account: perform account related actions
    clt account add <short_name>
    clt account returns --plot

watch: setup and maintain a watchlist for the current context
    clt watch <name> # add the specified stock to the watch list
    clt watch edit <name> --notes  # add some notes to the stock

position: manage positions
    clt position enter <A>,<B>,<C>,...  # enter multiple positions at once
    clt position exit <A>,<B>,<C>,...  # exit multiple positions at once
    clt position edit <name> --notes  # add some notes to the position
    clt position edit <name> --stop  # add some notes to the position
    
'''


@click.group()
@click.pass_context
def cli(ctx):
    conf = config.load_config()
    context_ = context.load_context(conf.context)
    ctx.obj = {
        'config': conf,
        'context': context_
    }


cli.add_command(context.context)
cli.add_command(account.account)
cli.add_command(position.position)
cli.add_command(chart.chart)
cli.add_command(watch.watch)
cli.add_command(market.market)

if __name__ == '__main__':
    cli()
