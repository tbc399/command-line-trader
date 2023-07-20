import os
from pathlib import Path
from typing import List

import click
import pydantic
import yaml

from clt import broker as br
from clt.config import BASE_DIR

__context_dir = os.path.join(BASE_DIR, "context")


class Account(pydantic.BaseModel):
    name: str
    broker: str
    number: str
    token: str


class WatchlistItem(pydantic.BaseModel):
    name: str
    notes: str

    def __eq__(self, value):
        if type(value) == str:
            return self.name.lower() == value.lower()
        return False


class Context(pydantic.BaseModel):
    name: str
    account: Account
    watchlist: List[WatchlistItem]

    @property
    def broker(self):
        return getattr(br, self.account.broker)(
            account_number=self.account.number,
            access_token=self.account.token,
            env="api",  # TODO: This is obviously hardcoded. Need to change
        )

    def __del__(self):
        save_context(self)


def save_context(context_: Context):
    context_file = os.path.join(__context_dir, f"{context_.name}.yaml")

    with open(context_file, "w") as file:
        try:
            yaml.dump(context_.dict(), file)
        except yaml.YAMLError as error:
            print(error)


def load_context(context_name: str):
    context_file = os.path.join(__context_dir, f"{context_name}.yaml")

    with open(context_file, "r") as file:
        try:
            context_yaml = yaml.safe_load(file)
        except yaml.YAMLError as error:
            print(error)

    return Context(**context_yaml)


@click.group()
def context():
    pass


@context.command()
@click.argument("name")
@click.pass_context
def switch(ctx, name):
    if ctx.invoked_subcommand is not None:
        return

    home_dir = os.environ["HOME"]
    clt_dir = ".clt"
    clt_base_dir = os.path.join(home_dir, clt_dir)
    context_dir = os.path.join(clt_base_dir, "context")

    if not os.path.exists(context_dir):
        os.makedirs(context_dir)

    context_file = os.path.join(context_dir, f"{name}.yaml")

    if not os.path.exists(context_file):
        click.echo(f"'{name}' is not a context!")
        return

    ctx.obj.get("config").save()

    click.echo(f"Switched context to '{name}'")


@context.command(name="new")
@click.argument("name")
@click.option("-d", "--description")
def new_context(name: str, description: str):
    home_dir = os.environ["HOME"]
    clt_dir = ".clt"
    clt_base_dir = os.path.join(home_dir, clt_dir)
    context_dir = os.path.join(clt_base_dir, "context")

    if not os.path.exists(context_dir):
        os.makedirs(context_dir)

    context_file = os.path.join(context_dir, f"{name}.yaml")
    with open(context_file, "w") as f:
        f.write(f"# {name}\n")
        if description:
            f.write(f"# {description}\n")

    click.echo(clt_base_dir)


@context.command()
@click.argument("name")
def rm(name: str):
    home_dir = os.environ["HOME"]
    clt_dir = ".clt"
    clt_base_dir = os.path.join(home_dir, clt_dir)
    context_dir = os.path.join(clt_base_dir, "context")

    if not os.path.exists(context_dir):
        os.makedirs(context_dir)

    Path(context_dir)
    os.remove()


@context.command(name="list")
def list_():
    home_dir = os.environ["HOME"]
    clt_dir = ".clt"
    clt_base_dir = os.path.join(home_dir, clt_dir)
    context_dir = os.path.join(clt_base_dir, "context")

    if not os.path.exists(context_dir):
        os.makedirs(context_dir)

    context_files = Path(context_dir).glob("*")

    for file in context_files:
        click.echo(file.name.split(".")[0])
