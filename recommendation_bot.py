# Setup section

import yaml
from box import ConfigBox

with open('keys.yaml', 'r') as config_file:
    config = ConfigBox(yaml.safe_load(config_file))
DISCORD_TOKEN = config.discord_bot_token
OMDB_API_KEY = config.OMDB_api_token
YOUR_GUILD_ID = config.GUILD_ID

import discord
from discord.ui import View, Button
from discord import Interaction
from discord.ext import commands, tasks
import requests
import json
import pytz
import pycountry
import asyncio
from datetime import datetime, UTC
from imdb import IMDb

shutdown_in_progress = False

# File to store recommendations, queue, and watchlist
RECOMMENDATIONS_FILE = "recommendations.json"
QUEUE_FILE = "queue.json"
WATCHLIST_FILE = "watchlist.json"
TIMEZONE_FILE = "timezones.json"

# Intents and bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Helper functions

class ConfirmationView(View):
    def __init__(self, author, action):
        super().__init__(timeout=60)
        self.author = author
        self.value = None
        self.action = action

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: Interaction, button: Button):
        if interaction.user == self.author:
            self.value = True
            await interaction.response.send_message(
                f"Confirmed! Proceeding to {self.action}.", ephemeral=True
            )
            self.stop()
        else:
            await interaction.response.send_message(
                "This confirmation is not for you.", ephemeral=True
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: Button):
        if interaction.user == self.author:
            self.value = False
            await interaction.response.send_message(
                "Action cancelled.", ephemeral=True
            )
            self.stop()
        else:
            await interaction.response.send_message(
                "This confirmation is not for you.", ephemeral=True
            )

def has_recommend_admin():
    """Custom check to see if the user has the 'recommend-admin' role."""
    async def predicate(ctx):
        return "recommend-admin" in [role.name for role in ctx.author.roles]
    return commands.check(predicate)

# Helper function to get IMDB id from Movie name
def get_imdb_id_from_name(movie_name):
    ia = IMDb()
    # Search for the movie by name
    movies = ia.search_movie(movie_name)
    if movies:
        # Get the IMDb ID of the first movie in the search results
        imdb_id = movies[0].movieID
        return imdb_id
    else:
        return None

# Helper function to fetch movie details from OMDb API
def fetch_movie_details(movie_name):
    movie_id = get_imdb_id_from_name(movie_name)
    url = f"http://www.omdbapi.com/?i=tt{movie_id}&apikey={OMDB_API_KEY}"
    response = requests.get(url)
    return response.json()

def load_country_aliases(filename='country_aliases.json'):
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Error: The file {filename} was not found.")
        return {}
    except json.JSONDecodeError:
        print(f"Error: The file {filename} is not a valid JSON.")
        return {}

# Load timezones from file
def load_timezones():
    try:
        with open(TIMEZONE_FILE, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

# Save timezones to file
def save_timezones(timezones):
    with open(TIMEZONE_FILE, "w") as file:
        json.dump(timezones, file, indent=4)

# Helper function to load recommendations from file
def load_recommendations():
    try:
        with open(RECOMMENDATIONS_FILE, "r") as file:
            loaded_json =  json.load(file)
        # print(f"Loaded Recommendation: \n{loaded_json}")
        return loaded_json
    except FileNotFoundError:
        return {}

# Helper function to save recommendations to file
def save_recommendations(data):
    # print(f"Saved Recommendations:\n{data}")
    with open(RECOMMENDATIONS_FILE, "w") as file:
        json.dump(data, file, indent=4)

# Load queue from file
def load_queue():
    try:
        with open(QUEUE_FILE, "r") as file:
            loaded_json =  json.load(file)
        # print(f"Loaded Queue: \n{loaded_json}")
        return loaded_json
    except FileNotFoundError:
        return []

# Save queue to file
def save_queue(data):
    # print(f"Saved Queue:\n{data}")
    with open(QUEUE_FILE, "w") as file:
        json.dump(data, file, indent=4)

# Load watchlist from file
def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as file:
            loaded_json =  json.load(file)
        # print(f"Loaded Watched List: \n{loaded_json}")
        return loaded_json
    except FileNotFoundError:
        return []

# Save watchlist to file
def save_watchlist(data):
    # print(f"Saved Watched List:\n{data}")
    with open(WATCHLIST_FILE, "w") as file:
        json.dump(data, file, indent=4)

def reload_lists(name=None):
    """Function to reload the global lists that the bot uses"""
    # Reload the global variables
    global recommendations, queue, watchlist, watched_titles

    # Block for recommendations reload
    if name == 'recommends' or name is None:
        recommendations = load_recommendations()
    
    # Block for queue reload
    if name == 'queue' or name is None:
        queue = load_queue()
    
    # Block for watchlist reload
    if name == 'watchlist' or name is None:
        watchlist = load_watchlist()
        watched_titles = [movie['title'] for movie in watchlist]

def get_timezones_by_country(country_code):
    """
    Get a list of timezones for a given country code.

    Args:
        country_code (str): The two-letter country code (ISO 3166-1 alpha-2).

    Returns:
        list: A list of timezones for the country or an error message if invalid.
    """
    try:
        # Convert country code to uppercase to handle case insensitivity
        country_code = country_code.upper()

        # Get timezones for the country
        timezones = pytz.country_timezones.get(country_code)
        if timezones:
            return timezones
        else:
            return f"No timezones found for country code `{country_code}`."
    except Exception as e:
        return f"An error occurred: {e}"

def get_country_code(country_name):
    """
    Get the ISO 3166-1 alpha-2 country code for a given country name.

    Args:
        country_name (str): The full name of the country.

    Returns:
        str: The country code if found, or None if the country is invalid.
    """
    # Normalize the input to lowercase
    country_name = country_name.lower()

    # Check if the country name is in the aliases
    if country_name in COMMON_COUNTRY_ALIASES:
        country_name = COMMON_COUNTRY_ALIASES[country_name]

    try:
        country = pycountry.countries.lookup(country_name)
        return country.alpha_2
    except LookupError:
        return None

def get_timezones_by_country_name(country_name):
    """
    Get a list of timezones for a given country name.

    Args:
        country_name (str): The full name of the country.

    Returns:
        str: A list of timezones or an error message if invalid.
    """
    # Get the country code from the name
    country_code = get_country_code(country_name)
    if not country_code:
        return f"Invalid country name: `{country_name}`."

    # Fetch timezones using the country code
    timezones = pytz.country_timezones.get(country_code)
    if timezones:
        return timezones
    else:
        return f"No timezones found for country: `{country_name}`."

# Initializing recommendations, queue, and watchlist
recommendations = load_recommendations()
queue = load_queue()
watchlist = load_watchlist()
watched_titles = [movie['title'] for movie in watchlist]

# Load the country aliases from the JSON file
COMMON_COUNTRY_ALIASES = load_country_aliases()

# Commands

## Commands for time and scheduling

@bot.command(name="country_code_timezones", aliases=["cctz", "timezones_by_country_code"])
async def countrycode_timezones(ctx, country_code: str):
    """
    Get a list of timezones for a specific country.
    """
    if not await check_channel(ctx):
        return

    timezones = get_timezones_by_country(country_code)
    
    if isinstance(timezones, list):
        timezone_list = "\n".join(timezones)
        await ctx.send(f"Timezones for `{country_code.upper()}`:\n```\n{timezone_list}\n```")
    else:
        await ctx.send(timezones)

@bot.command(name="country_name_timezones", aliases=["cntz", "timezones_by_country_name"])
async def countryname_timezones(ctx, *, country_name: str):
    """
    Get a list of timezones for a specific country by name.
    """
    if not await check_channel(ctx):
        return

    timezones = get_timezones_by_country_name(country_name)
    
    if isinstance(timezones, list):
        timezone_list = "\n".join(timezones)
        await ctx.send(f"Timezones for `{country_name.title()}`:\n```\n{timezone_list}\n```")
    else:
        await ctx.send(timezones)

# Command to set timezone
@bot.command(name="settime", aliases=['time'])
@has_recommend_admin()
async def set_timezone(ctx, timezone: str):
    """Set the admin's timezone."""
    if not await check_channel(ctx):
        return

    try:
        # Validate the timezone
        pytz.timezone(timezone)

        # Load existing timezones
        timezones = load_timezones()

        # Update the timezone for the admin
        timezones[str(ctx.author.id)] = timezone

        # Save the updated timezones
        save_timezones(timezones)

        await ctx.send(f"Your timezone has been set to `{timezone}`.")
    except pytz.UnknownTimeZoneError:
        await ctx.send(f"Invalid timezone: `{timezone}`. Please use a valid timezone.")

# Command to add time to a movie
@bot.command(name="addtime", aliases=['at'])
@has_recommend_admin()
async def add_time(ctx, movie_name: str, local_time: str):
    """Add time to a movie using the admin's timezone."""
    global queue
    if not await check_channel(ctx):
        return
    
    try:
        # Load the admin's timezone
        timezones = load_timezones()
        admin_timezone = timezones.get(str(ctx.author.id), "UTC")  # Default to UTC if not set
        user_timezone = pytz.timezone(admin_timezone)

        # Parse the local time and localize it
        naive_time = datetime.strptime(local_time, "%d-%m-%Y %H:%M")
        aware_time = user_timezone.localize(naive_time)
        unix_time = int(aware_time.timestamp())

        for movie in queue:
            if movie["title"].lower() == movie_name.lower():
                movie["time"] = unix_time
                break
        else:
            await ctx.send(f"Movie `{movie_name}` not found in the queue.")
            return

        save_queue(queue)

        # Update the recommendation channel with the latest data
        channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
        if channel:
            await update_recommendation_channel(channel, section="queue")

        # Notify the user
        embed = discord.Embed(
            title=f"🎥 Time for `{movie["title"]}` set to <t:{unix_time}:F> 🎥 in <t:{unix_time}:R>",
            description=f"**{movie['title']}** (Released: {movie['release_year']})\n"
                        f"Runtime: {movie['runtime']}\n"
                        f"Recommended by: {movie['recommended_by']}",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    except ValueError:
        await ctx.send("Invalid time format. Please use `DD-MM-YYYY HH:MM`.")
    except pytz.UnknownTimeZoneError:
        await ctx.send("There was an error with your timezone settings. Please reconfigure using `!set_timezone`.")

@bot.command(name="next_movie", aliases=["upcoming", "nm"])
async def show_next_movie(ctx):
    """Show the next upcoming movie in the queue based on the scheduled time, including the poster."""
    if not queue:
        await ctx.send("The queue is empty.")
        return

    # Filter movies with a valid time and sort by time
    upcoming_movies = sorted(
        (movie for movie in queue if "time" in movie and movie["time"]),
        key=lambda m: m["time"]
    )

    if upcoming_movies:
        next_movie = upcoming_movies[0]
        embed = discord.Embed(
            title="Next Upcoming Movie",
            description=(
                f"**{next_movie['title']}**\n"
                f"Release Year: {next_movie['release_year']}\n"
                f"Runtime: {next_movie['runtime']} minutes\n"
                f"Recommended By: {next_movie['recommended_by']}\n"
                f"Scheduled At: <t:{next_movie['time']}:f>\n"
                f"**Starts in <t:{next_movie['time']}:R>**\n"
            ),
            color=discord.Color.blue()
        )

        # Add the poster URL if available
        if "poster_url" in next_movie and next_movie["poster_url"]:
            embed.set_image(url=next_movie["poster_url"])

        await ctx.send(embed=embed)
    else:
        await ctx.send("No upcoming movies are scheduled in the queue.")


## Commands for Queue

@bot.command(name="queue", aliases=['q'])
@has_recommend_admin()
async def add_to_queue(ctx, *, movie_name):

    if not await check_channel(ctx):
        return

    if movie_name not in recommendations:
        await ctx.send(f"The movie `{movie_name}` is not in the recommendations list.")
        return

    # Add the movie to the queue, inheriting details from recommendations
    movie_data = recommendations.pop(movie_name)
    queue.append({
        "title": movie_name,
        "release_year": movie_data["release_year"],
        "runtime": movie_data["runtime"],
        "recommended_by": movie_data["recommended_by"],
        "poster_url": movie_data["poster_url"]
    })
    save_recommendations(recommendations)
    save_queue(queue)

    channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
    if channel:
        await update_recommendation_channel(channel, section='queue')

    await ctx.send(f"The movie `{movie_name}` has been added to the queue.")

@bot.command(name="announce", aliases=['am'])
@has_recommend_admin()
async def announce_playing_movie(ctx, *, movie_name: str):
    # Check if the movie is in the queue
    if not await check_channel(ctx):
        return

    movie_to_watch = next((movie for movie in queue if movie["title"] == movie_name), None)
    
    if not movie_to_watch:
        await ctx.send(f"The movie `{movie_name}` is not in the queue!")
        return

    # Create the announcement embed
    embed = discord.Embed(
        title="🎥 Now Playing 🎥",
        description=f"**{movie_to_watch['title']}** (Released: {movie_to_watch['release_year']})\n"
                    f"Runtime: {movie_to_watch['runtime']}\n"
                    f"Recommended by: {movie_to_watch['recommended_by']}",
        color=discord.Color.blue()
    )
    embed.set_image(url=movie_to_watch["poster_url"])
    await ctx.send(embed=embed)


@bot.command(name="deleteq", aliases=['delq'])
@has_recommend_admin()
async def remove_from_queue(ctx, *, movie_name: str):

    # Check if the movie is in the queue
    if not await check_channel(ctx):
        return

    movie_to_remove = next((movie for movie in queue if movie["title"] == movie_name), None)

    if movie_to_remove:
        # Remove the movie from the queue
        queue.remove(movie_to_remove)
        save_queue(queue)

        # Update the recommendation channel with the latest data
        channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
        if channel:
            await update_recommendation_channel(channel, section="queue")

        await ctx.send(f"The movie `{movie_name}` has been removed from the queue.")
    else:
        await ctx.send(f"The movie `{movie_name}` is not in the queue.")

@bot.command(name="clearq")
@has_recommend_admin()
async def clear_queue(ctx):

    if not await check_channel(ctx):
        return

    queue.clear()
    save_queue(queue)

    channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
    if channel:
        # Update only the queue section
        await update_recommendation_channel(channel, section="queue")

    await ctx.send("The queue has been cleared.")

## Commands for Watchlist

@bot.command(name="watched", aliases=['w'])
@has_recommend_admin()
async def add_to_watchlist(ctx, *, movie_name):
    """Add a movie to the watchlist, checking queue, recommendations, or searching."""
    global watched_titles

    if not await check_channel(ctx):
        return

    # Search for the movie
    movie_data = fetch_movie_details(movie_name) 
    movie_title = movie_data.get("Title", "N/A")
    runtime = movie_data.get("Runtime", "N/A")
    poster_url = movie_data.get("Poster", None)
    release_year = movie_data.get("Year", "N/A")

    # Check if the movie exists in the queue
    for movie in queue:
        if movie["title"].lower() == movie_title.lower():
            queue.remove(movie)
            watchlist.append(movie)
            save_queue(queue)
            save_watchlist(watchlist)
            watched_titles = watched_titles.append(movie_name)
            await ctx.send(f"The movie `{movie_name}` has been moved from the queue to the watchlist.")
            
            # Update recommendation channel
            channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
            if channel:
                await update_recommendation_channel(channel, section='watchlist')
            return

    # Check if the movie exists in recommendations
    if movie_title in recommendations:
        # Pop up a confirmation window
        view = ConfirmationView(author=ctx.author, action="move the movie to the watchlist")
        message = await ctx.send(
            f"The movie `{movie_title}` is in recommendations. Do you want to move it to the watchlist?",
            view=view,
        )
        await view.wait()

        if view.value is True:
            movie_data = recommendations.pop(movie_name)
            watchlist.append(movie_data)
            save_recommendations(recommendations)
            save_watchlist(watchlist)
            watched_titles = watched_titles.append(movie_name)
            await ctx.send(f"The movie `{movie_name}` has been moved from recommendations to the watchlist.")
            
            # Update recommendation channel
            channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
            if channel:
                await update_recommendation_channel(channel, section='watchlist')
        elif view.value is None:
            await ctx.send("No response received. Action cancelled.")
        return

    if movie_data:
        view = ConfirmationView(author=ctx.author, action="add the movie directly to the watchlist")
        message = await ctx.send(
            f"Found `{movie_title}` (Release year: {release_year}, Runtime: {runtime} mins). "
            f"Do you want to add it to the watchlist?",
            view=view,
        )
        await view.wait()

        if view.value is True:
            watchlist.append({
                "title": movie_title,
                "release_year": release_year,
                "runtime": runtime,
                "recommended_by": ctx.author.name,
                "poster_url": poster_url
            })
            save_watchlist(watchlist)
            watched_titles = watched_titles.append(movie_name)
            await ctx.send(f"The movie `{movie_title}` has been added to the watchlist.")
            
            # Update recommendation channel
            channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
            if channel:
                await update_recommendation_channel(channel, section='watchlist')
        elif view.value is None:
            await ctx.send("No response received. Action cancelled.")
    else:
        await ctx.send(f"No results found for `{movie_name}`.")

# @bot.command(name="watched", aliases=['w'])
# @has_recommend_admin()
# async def add_to_watchlist(ctx, *, movie_name):

#     global watched_titles
#     if not await check_channel(ctx):
#         return
    
#     for movie in queue:
#         if movie["title"] == movie_name:
#             movie_data = movie
#             queue.remove(movie)
#             break
#     else:
#         await ctx.send(f"The movie `{movie_name}` is not in the queue.")
#         return

#     # Add the movie to the watchlist, inheriting details from queue
#     watchlist.append({
#         "title": movie_data["title"],
#         "release_year": movie_data["release_year"],
#         "runtime": movie_data["runtime"],
#         "recommended_by": movie_data["recommended_by"],
#         "poster_url": movie_data["poster_url"]
#     })
#     save_queue(queue)
#     save_watchlist(watchlist)
#     watched_titles = watched_titles.append(movie_name)

#     channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
#     if channel:
#         await update_recommendation_channel(channel, section='watchlist')

#     await ctx.send(f"The movie `{movie_name}` has been moved to the watchlist.")

@bot.command(name="deletew", aliases=['delw'])
@has_recommend_admin()
async def remove_from_watchlist(ctx, *, movie_name: str):

    global watched_titles
    if not await check_channel(ctx):
        return

    # Check if the movie is in the watchlist
    movie_to_remove = next((movie for movie in watchlist if movie["title"] == movie_name), None)

    if movie_to_remove:
        # Remove the movie from the watchlist
        watchlist.remove(movie_to_remove)
        save_watchlist(watchlist)
        watched_titles = [movie['title'] for movie in watchlist]

        # Update the recommendation channel with the latest data
        channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
        if channel:
            await update_recommendation_channel(channel, section="watchlist")

        await ctx.send(f"The movie `{movie_name}` has been removed from the watchlist.")
    else:
        await ctx.send(f"The movie `{movie_name}` is not in the watchlist.")

@bot.command(name="clearw")
@commands.has_permissions(administrator=True)
async def clear_watchlist(ctx):

    global watched_titles
    if not await check_channel(ctx):
        return

    watchlist.clear()
    save_watchlist(watchlist)
    watched_titles = []

    channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
    if channel:
        # Update only the watchlist section
        await update_recommendation_channel(channel, section="watchlist")

    await ctx.send("The watched list has been cleared.")

## Commands for Recommendations

@bot.command(name="recommend", aliases=['r'])
async def recommend(ctx, *, movie_name: str):
    
    global watched_titles
    if not await check_channel(ctx):
        return

    if len(recommendations) >= 20:
        await ctx.send("The recommendations list is full (20 movies). Please wait until some movies are removed before recommending more.")
        return

    movie_data = fetch_movie_details(movie_name)
    
    movie_in_queue = next((movie for movie in queue if movie["title"] == movie_data.get('Title', 'N/A')), None)

    if movie_in_queue:
        await ctx.send(f"The movie `{movie_name}` is already in queue scheduled at <t:{movie_data['time']}:f>")
        return

    if movie_data.get('Title', 'N/A') in watched_titles:
        await ctx.send(f"{movie_name} has already been watched. Ask admins for rewatching.")
        return
    
    if movie_data.get("Response") == "True":
        if movie_data.get('Title', 'N/A') not in recommendations:
            # Fetch necessary details
            movie_title = movie_data.get("Title", "N/A")
            runtime = movie_data.get("Runtime", "N/A")
            poster_url = movie_data.get("Poster", None)
            release_year = movie_data.get("Year", "N/A")
            plot = movie_data.get("Plot", "No plot information available.")
            imdb_id = movie_data.get("imdbID", None)

            imdb_url = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "No IMDb link available"

            
            # Store the movie details along with votes and recommender
            recommendations[movie_title] = {
                "recommended_by": ctx.author.name,
                "votes": 0,
                "voters": [],
                "runtime": runtime,
                "poster_url": poster_url,
                "release_year": release_year
            }

            save_recommendations(recommendations)

            # Update the recommendation channel with the new movie
            channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
            if channel:
                await update_recommendation_channel(channel, section='recommendations')
            embed = discord.Embed(
                title=movie_title,
                description=plot,
                color=discord.Color.blue(),
                url=imdb_url
            )
            embed.add_field(name="Runtime", value=runtime, inline=True)
            embed.add_field(name="Release Year", value=release_year, inline=True)
            embed.add_field(name="Recommended By", value=ctx.author.name, inline=True)
            embed.set_thumbnail(url=poster_url)
            embed.set_footer(text=f"Votes: 0")

            await ctx.send(f"'{movie_name}' has been added to the recommendations!")
            await ctx.send(embed=embed)
        else:
            # Movie already recommended, handle voting
            movie = recommendations[movie_name]
            
            if ctx.author.id in movie["voters"]:
                await ctx.send(f"You've already voted for '{movie_name}'. You can only vote once.")
                return
            
            # Check if the user is the recommender
            if ctx.author.name == movie["recommended_by"]:
                await ctx.send(f"You cannot vote for your own recommendation, '{movie_name}'.")
                return

            # Add the user to the voters list and increment the vote
            movie["voters"].append(ctx.author.id)
            movie["votes"] += 1
            save_recommendations(recommendations)

            await ctx.send(f"You've voted for '{movie_name}'. It now has {movie['votes']} votes.")
    else:
        await ctx.send("Sorry, I couldn't find that movie.")

@bot.command(name="vote")
async def vote_movie(ctx, *, movie_name: str):

    global recommendations
    if not await check_channel(ctx):
        return

    if movie_name in recommendations:
        movie = recommendations[movie_name]
         
        if ctx.author.id in movie["voters"]:
            await ctx.send(f"You've already voted for '{movie_name}'. You can only vote once.")
            return
        
        # Check if the user is the recommender
        if ctx.author.name == movie["recommended_by"]:
            await ctx.send(f"You cannot vote for your own recommendation, '{movie_name}'.")
            return
        
        # Add the user to the voters list and increment the vote
        movie["voters"].append(ctx.author.id)
        movie["votes"] += 1
        save_recommendations(recommendations)
        
        # Update the recommendation channel with the new movie
        channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
        if channel:
            await update_recommendation_channel(channel, section='recommendations')
            
        await ctx.send(f"Thank you! You've voted for '{movie_name}'. It now has {movie['votes']} votes.")
    else:
        await ctx.send(f"The movie `{movie_name}` is not in the recommended list.")

# Remove a movie recommendation (User can remove only their own recommendations)
@bot.command(name="delete", aliases=['del'])
async def remove_recommendation(ctx, *, movie_name: str):
    if not await check_channel(ctx):
        return

    if movie_name in recommendations:
        # Check if the user who is requesting removal is the one who recommended it or has admin privileges
        if recommendations[movie_name]["recommended_by"] == ctx.author.name or ("recommend-admin" in [role.name for role in ctx.author.roles]):
            del recommendations[movie_name]
            save_recommendations(recommendations)

            # Update the recommendation channel
            channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
            if channel:
                await update_recommendation_channel(channel, section='recommendations')

            await ctx.send(f"'{movie_name}' has been removed from the recommendations.")
        else:
            await ctx.send(f"You cannot remove '{movie_name}' because you did not recommend it.")
    else:
        await ctx.send(f"'{movie_name}' is not in the recommendations list.")

@bot.command(name="clearrec")
@has_recommend_admin()
async def clear_recommendation(ctx):

    global recommendations
    if not await check_channel(ctx):
        return
    
    recommendations.clear()
    save_recommendations(recommendations)
        
    # Fetch the latest message from the channel
    channel = discord.utils.get(ctx.guild.text_channels, name="movie-recommendations")
    if channel:
        async for message in channel.history(limit=10):
            if message.author == bot.user:
                # Get the embed from the message
                embed = message.embeds[0] if message.embeds else discord.Embed(title="Movie Recommendations", color=discord.Color.green())
                
                # Find and remove the recommendation field (index 0)
                # Ensure that we only clear the "Recommendations" section
                if len(embed.fields) > 0 and embed.fields[0].name == "Recommendations":
                    embed.set_field_at(0, name="Recommendations", value="No movies recommended yet.", inline=False)

                    # Edit the message to reflect the changes (only clearing the recommendation section)
                    await message.edit(embed=embed)
                    await ctx.send("The recommendation section has been cleared.")
                    return

    # If no appropriate message is found, send a message indicating nothing was found
    await ctx.send("All recommendation are cleared.")

## Display commands

@bot.command(name="displayrec", aliases=['dr', 'display'])
async def display_recommendations(ctx):
    # Ensure recommendations exist
    if not recommendations:
        await ctx.send("No recommendations available at the moment.")
        return

    # Create an embed for the top 5 recommendations
    embed = discord.Embed(title="Top 5 Movie Recommendations", color=discord.Color.blue())
    
    # Sort and display the top 5 recommendations by votes
    top_recommendations = sorted(recommendations.items(), key=lambda item: item[1]['votes'], reverse=True)[:5]
    for i, (name, data) in enumerate(top_recommendations, start=1):
        embed.add_field(
            name=f"{i}. {name}",
            value=(
                f"Release Year: {data['release_year']}\n"
                f"Runtime: {data['runtime']}\n"
                f"Recommended By: {data['recommended_by']}\n"
                f"Votes: {data['votes']}\n"
            ),
            inline=False
        )

    # Send the embed
    await ctx.send(embed=embed)

@bot.command(name="displayqueue", aliases=['dq', 'displayq'])
async def display_queue(ctx):
    if not queue:
        await ctx.send("The queue is empty.")
        return

    # Create an embed for the queue
    embed = discord.Embed(title="Movie Queue", color=discord.Color.green())
    sorted_queue = sorted(queue, key=lambda m: m.get('time', float('inf')))

    for i, movie in enumerate(sorted_queue, start=1):
        embed.add_field(
            name=f"{i}. {movie['title']}",
            value=(
                f"Release Year: {movie['release_year']}\n"
                f"Runtime: {movie['runtime']}\n"
                f"Recommended By: {movie['recommended_by']}\n"
                + (f"Scheduled At: <t:{movie['time']}:f>\n" if 'time' in movie and movie['time'] else "Movie Not Scheduled yet\n")
            ),
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name="displaywatchlist", aliases=['dw', 'displayw'])
async def display_watchlist(ctx):
    if not watchlist:
        await ctx.send("The watchlist is empty.")
        return

    # Create an embed for the watchlist
    embed = discord.Embed(title="Movies Watched List", color=discord.Color.purple())
    for i, movie in enumerate(watchlist[-5:], start=1):
        embed.add_field(
            name=f"{i}. {movie['title']}",
            value=(
                f"Release Year: {movie['release_year']}\n"
                f"Runtime: {movie['runtime']}\n"
                f"Recommended By: {movie['recommended_by']}\n"
            ),
            inline=False
        )

    await ctx.send(embed=embed)

## Management commands and functions

@tasks.loop(seconds=60)  # Check every 60 seconds
async def announce_scheduled_movies():
    if not queue:
        return  # Skip if the queue is empty

    current_time = datetime.now(UTC)  # Get the current time in UTC
    current_day_time_hour = (current_time.year, current_time.month, current_time.day, current_time.hour, current_time.minute)
    for movie in queue[:]:  # Iterate over a copy of the queue to allow removal
        if "time" in movie:
            movie_time = datetime.utcfromtimestamp(movie["time"])
            movie_day_time_hour = (movie_time.year, movie_time.month, movie_time.day, movie_time.hour, movie_time.minute)
            # Fetch the channel where the announcements will be sent
            guild = bot.get_guild(YOUR_GUILD_ID)  # Replace with your server's ID
            announcement_channel = discord.utils.get(guild.text_channels, name="movie-recommendations")
            
            if announcement_channel and movie_day_time_hour == current_day_time_hour:
                # Create the announcement embed
                embed = discord.Embed(
                    title="🎥 Now Playing 🎥",
                    description=f"**{movie['title']}** (Released: {movie['release_year']})\n"
                                f"Runtime: {movie['runtime']}\n"
                                f"Recommended by: {movie['recommended_by']}",
                    color=discord.Color.blue()
                )
                embed.set_image(url=movie.get("poster_url", ""))
                await announcement_channel.send(embed=embed)

            # Remove the movie from the queue after announcement
            queue.remove(movie)
            save_queue(queue)  # Save the updated queue

async def cycle_recommendation_channel(channel):
    sections = ["recommendations", "queue", "watchlist"]
    section_index = 0

    while True:
        # Get the current section to update
        current_section = sections[section_index]

        # Call the update function with the current section
        await update_recommendation_channel(channel, section=current_section)

        # Cycle to the next section
        section_index = (section_index + 1) % len(sections)

        # Wait for 10 seconds before updating the next section
        await asyncio.sleep(10)

async def update_recommendation_channel(channel, section=None):

    reload_lists(section)
    async for message in channel.history(limit=10):
        if message.author == bot.user:
            embed = discord.Embed(color=discord.Color.green())

            # Set the title based on the current section
            if section == "recommendations":
                embed.title = "Movie Recommendations"
                if len(recommendations) > 0:
                    recommendations_display = "\n".join(
                        [f"**{name}**\nRelease year: {data['release_year']}\nRuntime: {data['runtime']}\nRecommended by: {data['recommended_by']}\nVotes: {data['votes']}\n"
                         for name, data in sorted(recommendations.items(), key=lambda item: item[1]['votes'], reverse=True)]
                    )
                    embed.description = recommendations_display
                else:
                    embed.description = "No movies recommended yet."

            elif section == "queue":
                embed.title = "Movie Queue"
                if queue:
                    queue_display = "\n".join(
                        [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
                         f"{f'Scheduled at: <t:{movie['time']}:f>\n' if 'time' in movie and movie['time'] else ''}"
                         for movie in sorted(queue, key=lambda m: m.get('time', float('inf')))]
                    )
                    embed.description = queue_display
                else:
                    embed.description = "The queue is empty."

            elif section == "watchlist":
                embed.title = "Movies Watched list"
                if watchlist:
                    if len(watchlist) > 10:
                        watchlist_display = "\n".join(
                            [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
                             for movie in watchlist[-10]]
                        )
                    else:
                        watchlist_display = "\n".join(
                            [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
                             for movie in watchlist]
                        )
                    embed.description = watchlist_display
                else:
                    embed.description = "The watchlist is empty."

            # Edit the message with the updated embed
            await message.edit(embed=embed)
            return

    # If no previous message exists, create a new embed and send it
    embed = discord.Embed(color=discord.Color.green())
    if section == "recommendations":
        embed.title = "Movie Recommendations"
        if len(recommendations) > 0:
            recommendations_display = "\n".join(
                [f"**{name}**\nRelease year: {data['release_year']}\nRuntime: {data['runtime']}\nRecommended by: {data['recommended_by']}\nVotes: {data['votes']}\n"
                 for name, data in sorted(recommendations.items(), key=lambda item: item[1]['votes'], reverse=True)]
            )
            embed.description = recommendations_display
        else:
            embed.description = "No movies recommended yet."

    elif section == "queue":
        embed.title = "Movie Queue"
        if queue:
            queue_display = "\n".join(
                [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
                 f"{f'Scheduled at: <t:{movie['time']}:f>\n' if 'time' in movie and movie['time'] else ''}"
                 for movie in sorted(queue, key=lambda m: m.get('time', float('inf')))]
            )
            embed.description = queue_display
        else:
            embed.description = "The queue is empty."

    elif section == "watchlist":
        embed.title = "Movies Watched list"
        if watchlist:
            watchlist_display = "\n".join(
                [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
                 for movie in watchlist[-10:]]
            )
            embed.description = watchlist_display
        else:
            embed.description = "The watchlist is empty."

    await channel.send(embed=embed)

# async def update_recommendation_channel(channel, section=None):
#     # Fetch the latest message sent by the bot
#     async for message in channel.history(limit=10):
#         if message.author == bot.user:
#             # Get the existing embed or create a new one
#             embed = message.embeds[0] if message.embeds else discord.Embed(title="Movie Recommendations", color=discord.Color.green())
            
#             # Ensure all fields exist or add them as placeholders
#             field_names = ["Recommendations", "Queue", "Watchlist"]
#             while len(embed.fields) < len(field_names):
#                 embed.add_field(name="Placeholder", value="...", inline=False)

#             # Update the fields dynamically based on the section
#             if section in ("recommendations", None):
#                 if recommendations:
#                     recommendations_display = "―" * 25 + "\n" + "\n".join(
#                         [f"**{name}**\nRelease year: {data['release_year']}\nRuntime: {data['runtime']}\nRecommended by: {data['recommended_by']}\nVotes : {data['votes']}\n"
#                          for name, data in sorted(recommendations.items(), key=lambda item: item[1]['votes'], reverse=True)]
#                     ) + "\n" + "―" * 25
#                     embed.set_field_at(0, name="Recommendations", value=recommendations_display, inline=False)
#                 else:
#                     embed.set_field_at(0, name="Recommendations", value="No movies recommended yet.", inline=False)

#             if section in ("queue", None):
#                 if queue:
#                     queue_display = "―" * 25 + "\n" + "\n".join(
#                         [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
#                          f"{f'Scheduled at: <t:{movie["time"]}:f>\n' if 'time' in movie and movie['time'] else ''}"
#                          for movie in sorted(queue, key=lambda m: m.get('time', float('inf')))]
#                     ) + "\n" + "―" * 25
#                     embed.set_field_at(1, name="Queue", value=queue_display, inline=False)
#                 else:
#                     embed.set_field_at(1, name="Queue", value="The queue is empty.", inline=False)

#             if section in ("watchlist", None):
#                 if watchlist:
#                     watchlist_display = "―" * 25 + "\n" + "\n".join(
#                         [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
#                          for movie in watchlist]
#                     ) + "\n" + "―" * 25
#                     embed.set_field_at(2, name="Watchlist", value=watchlist_display, inline=False)
#                 else:
#                     embed.set_field_at(2, name="Watchlist", value="The watchlist is empty.", inline=False)

#             # Edit the message with the updated embed
#             await message.edit(embed=embed)
#             return

#     # If no previous message exists, create a new embed and send it
#     embed = discord.Embed(title="Movie Recommendations", color=discord.Color.green())
#     if section in ("recommendations", None) and recommendations:
#         embed.add_field(
#             name="Recommendations",
#             value="―" * 25 + "\n" + "\n".join(
#                 [f"**{name}**\nRelease year: {data['release_year']}\nRuntime: {data['runtime']}\nRecommended by: {data['recommended_by']}\nVotes : {data['votes']}\n"
#                  for name, data in sorted(recommendations.items(), key=lambda item: item[1]['votes'], reverse=True)]
#             ) + "\n" + "―" * 25,
#             inline=False,
#         )
#     elif section in ("recommendations", None):
#         embed.add_field(name="Recommendations", value="No movies recommended yet.", inline=False)

#     if section in ("queue", None) and queue:
#         embed.add_field(
#             name="Queue",
#             value="―" * 25 + "\n" + "\n".join(
#                 [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
#                  f"{f'Scheduled at: <t:{movie["time"]}:f>\n' if 'time' in movie and movie['time'] else ''}"
#                  for movie in sorted(queue, key=lambda m: m.get('time', float('inf')))]
#             ) + "\n" + "―" * 25,
#             inline=False,
#         )
#     elif section in ("queue", None):
#         embed.add_field(name="Queue", value="The queue is empty.", inline=False)

#     if section in ("watchlist", None) and watchlist:
#         embed.add_field(
#             name="Watchlist",
#             value="―" * 25 + "\n" + "\n".join(
#                 [f"**{movie['title']}**\nRelease year: {movie['release_year']}\nRuntime: {movie['runtime']}\nRecommended by: {movie['recommended_by']}\n"
#                  for movie in watchlist]
#             ) + "\n" + "―" * 25,
#             inline=False,
#         )
#     elif section in ("watchlist", None):
#         embed.add_field(name="Watchlist", value="The watchlist is empty.", inline=False)

#     await channel.send(embed=embed)

@bot.command(name="shutdown", aliases=['exit', 'close', 'end', 'quit'])
@has_recommend_admin()
async def shutdown(ctx):
    global shutdown_in_progress  # Access the global flag

    if not await check_channel(ctx):
        return
    
    shutdown_in_progress = True  # Set the flag when the bot is shutting down
    
    await ctx.send("<:grass:1327507600379613194> Bidoof has been released to the wild (offline)")
    await bot.close()

@bot.command(name='manual_admin', aliases=['ha', 'commands_admin'])
@has_recommend_admin()
async def get_manual(ctx):

    if not await check_channel(ctx):
        return

    manual_string = """
```
ADMIN ONLY COMMANDS
-------------------------
Timezone Commands
-------------------------
country_code_timezones | cctz <Country Code>   -> Get timezone for country code
country_name_timezones | cntz <Country Name>   -> Get timezone for country by name
settime | time <Timezone>                      -> Set Timezone of recommend bot admin
addtime | at "<Movie Name>" "DD-MM-YYYY HH:MM" -> Schedule a movie

-------------------------
Recommendation Commands
-------------------------
delete | del <Movie Name>                     -> Remove movie from recommendation
clearrec                                      -> Clear Recommendations

-------------------------
Queue Commands
-------------------------
queue | q <Movie Name>                        -> Move movie to Queue
announce | am                                 -> Announce movie to watch
deleteq | delq <Movie Name>                   -> Remove movie from Queue
clearq                                        -> Clear Queue

-------------------------
Watched List Commands
-------------------------
watched | w <Movie Name>                      -> Move movie Watched List
deletew | delw <Movie Name>                   -> Remove movie from Watched List
clearw                                        -> Clear Watched list

-------------------------
Maintenance Commands
-------------------------
shutdown | exit | quit | close                -> Shutdown bot
manual_admin | commands_admin | ha            -> Get admin manual
manual | commands | h                         -> Get manual
```
    """

    # Try sending the message to the user's DM
    await ctx.send(manual_string)

@bot.command(name='manual', aliases=['h', 'commands'])
async def get_manual(ctx):

    if not await check_channel(ctx):
        return

    manual_string = """
```
-------------------------
Recommendation Commands
-------------------------
recommend | r <Movie Name>        -> Recommend a movie for Movie Night
vote <Movie Name>                 -> Vote for a movie in the recommendation list
delete | del <Movie Name>         -> Remove movie from recommendation

-------------------------
Display Commands
-------------------------
displayrec | dr | display         -> Display Top 5 Recommendations
displayqueue | dq | displayq      -> Display Queued Movies
displaywatchlist | dw | displayw  -> Display Latest 5 Watched Movies
next_movie | upcoming | nm        -> Display upcoming movie in queue

-------------------------
Maintenance Commands
-------------------------
manual | commands | h             -> Get manual
manual_admin | commands_admin| ha -> Get Admin Only commands
```
    """

    # Try sending the message to the user's DM
    await ctx.send(manual_string)

# Check if the command comes from the correct channel
async def check_channel(ctx):
    if ctx.channel.name != 'movie_night':
        await ctx.send("Please use the 'movie_night' channel to interact with the bot.")
        return False
    return True

# Events

@bot.event
async def on_command(ctx):
    print(f"Command detected: {ctx.command} - Triggered by: {ctx.author.name}")

# Explicitly define on_message to handle command processing
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

# Explicitly define on_disconnect to detect bot session pauses
# @bot.event
# async def on_disconnect():
#     global shutdown_in_progress
#     channel = discord.utils.get(bot.get_all_channels(), name='movie_night')
#     if channel and not shutdown_in_progress:
#         await channel.send(f"<:Bidoof:1327507372566122508> Bidoof is taking a break... (paused)")

# @bot.event
# async def on_resume():
#     print("The bot has resumed its connection to Discord.")
    
#     # You can also send a message to a channel when the bot resumes
#     channel = discord.utils.get(bot.get_all_channels(), name='movie_night')
#     if channel:
#         await channel.send(f"<:CHAD:1327507515759657006> Bidoof is ready to take commands again!")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    channel = discord.utils.get(bot.get_all_channels(), name='movie_night')
    if channel:
        await channel.send(f"<:pokeball:1327507572206600223> Bidoof  I choose you! (ready to be commanded)")
    
    # Load recommendations, queue, and watchlist from their respective JSON files
    global recommendations, queue, watchlist
    recommendations = load_recommendations()
    queue = load_queue()
    watchlist = load_watchlist()

    if not announce_scheduled_movies.is_running():
        announce_scheduled_movies.start()
    print(f"Bot is ready and monitoring scheduled movies.")
    
    # Find the "recommendation" channel
    channel = discord.utils.get(bot.get_all_channels(), name="movie-recommendations")
    if channel:
        bot.loop.create_task(cycle_recommendation_channel(channel))
        bot.loop.create_task(announce_scheduled_movies())
    
    # channel = discord.utils.get(bot.get_all_channels(), name="movie-recommendations")
    # if channel:
    #     async for message in channel.history(limit=100):  # Adjust the limit as needed
    #         if message.author == bot.user:
    #             await message.delete()
    #     await update_recommendation_channel(channel)


# Run the bot
bot.run(DISCORD_TOKEN)