import asyncio
import os
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

load_dotenv()


# BASE SCRAPER CLASS

class BaseScraper(ABC):
    # Abstract base class for all web scrapers
    
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
    
    @abstractmethod
    async def scrape(self, url: str) -> Dict:
        """
        Scrape the given URL and return results
        Must be implemented by all subclasses 
        """
        pass
    
    def format_output(self, time_taken: float, content: str) -> Dict:
    
        # Format the scraping output in standardized JSON format
        
        return {
            "tool_name": self.tool_name,
            "time_taken": round(time_taken, 3),
            "content_length": len(content),
            "content_snippet": content[:200].strip() if content else ""
        }


# PLAYWRIGHT SCRAPER

class PlaywrightScraper(BaseScraper):
    
    def __init__(self):
        super().__init__("Playwright")
    
    async def scrape(self, url: str) -> Dict:
        """
        Scrape using Playwright with headless browser
        Handles JavaScript rendering and waits for network idle
        """
        start_time = time.time()
        content = ""
        
        try:
            async with async_playwright() as p:
                # Launch headless browser
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                try:
                    # Navigate to URL with timeout
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    
                    # Wait for main content element (fallback to body if main doesn't exist)
                    try:
                        await page.wait_for_selector("main", timeout=5000)
                    except PlaywrightTimeoutError:
                        # If no main element, just wait for body
                        await page.wait_for_selector("body", timeout=5000)
                    
                    # Extract all text content from the page
                    content = await page.evaluate("() => document.body.innerText")
                    
                except PlaywrightTimeoutError as e:
                    raise Exception(f"Playwright timeout: {str(e)}")
                except Exception as e:
                    raise Exception(f"Playwright navigation error: {str(e)}")
                finally:
                    await browser.close()
                    
        except Exception as e:
            # Return error information in the same format
            time_taken = time.time() - start_time
            return {
                "tool_name": self.tool_name,
                "time_taken": round(time_taken, 3),
                "content_length": 0,
                "content_snippet": f"ERROR: {str(e)}",
                "error": str(e)
            }
        
        time_taken = time.time() - start_time
        
        if not content or len(content.strip()) == 0:
            raise Exception("Empty content returned")
        
        return self.format_output(time_taken, content)


# CRAWL4AI SCRAPER

class Crawl4AIScraper(BaseScraper):
    """Scraper using Crawl4AI Python SDK"""
    
    def __init__(self):
        super().__init__("Crawl4AI")
    
    async def scrape(self, url: str) -> Dict:
        """
        Scrape using Crawl4AI with async browser
        """
        start_time = time.time()
        content = ""
        
        try:
            from crawl4ai import AsyncWebCrawler
            import logging
            
            # Suppress Crawl4AI's verbose logging to prevent duplicate output
            logging.getLogger('crawl4ai').setLevel(logging.ERROR)
            
            # Create async crawler instance with verbose disabled
            async with AsyncWebCrawler(verbose=False, headless=True) as crawler:
                # Run the crawler - single execution
                result = await crawler.arun(url=url)
                
                # Check if crawl was successful
                if not result.success:
                    raise Exception(f"Crawl4AI failed: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                
                # Extract markdown or text content
                # Crawl4AI provides markdown by default
                content = result.markdown if hasattr(result, 'markdown') and result.markdown else ""
                
                # Fallback to extracted_content or html if markdown is empty
                if not content:
                    content = result.extracted_content if hasattr(result, 'extracted_content') else ""
                
                if not content:
                    raise Exception("No content extracted by Crawl4AI")
                    
        except ImportError:
            # Handle case where Crawl4AI is not installed
            time_taken = time.time() - start_time
            return {
                "tool_name": self.tool_name,
                "time_taken": round(time_taken, 3),
                "content_length": 0,
                "content_snippet": "ERROR: Crawl4AI not installed. Run: pip install crawl4ai",
                "error": "Module not found"
            }
        except Exception as e:
            time_taken = time.time() - start_time
            return {
                "tool_name": self.tool_name,
                "time_taken": round(time_taken, 3),
                "content_length": 0,
                "content_snippet": f"ERROR: {str(e)}",
                "error": str(e)
            }
        
        time_taken = time.time() - start_time
        return self.format_output(time_taken, content)


# FIRECRAWL SCRAPER

class FirecrawlScraper(BaseScraper):
    """Scraper using Firecrawl API"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__("Firecrawl")
        # Get API key from environment variable or parameter
        self.api_key = os.getenv("FIRECRAWL_API_KEY")
        self.base_url = "https://api.firecrawl.dev/v0/scrape"
    
    async def scrape(self, url: str) -> Dict:
        """
        Scrape using Firecrawl API
        Requires valid API key
        """
        start_time = time.time()
        content = ""
        
        # Check for API key
        if not self.api_key:
            time_taken = time.time() - start_time
            return {
                "tool_name": self.tool_name,
                "time_taken": round(time_taken, 3),
                "content_length": 0,
                "content_snippet": "ERROR: FIRECRAWL_API_KEY not set",
                "error": "Missing API key"
            }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Prepare request
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "url": url,
                    "pageOptions": {
                        "onlyMainContent": True
                    }
                }
                
                # Make API request
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers=headers
                )
                
                # Check response status
                if response.status_code == 401:
                    raise Exception("Invalid API key")
                elif response.status_code == 402:
                    raise Exception("API quota exceeded")
                elif response.status_code != 200:
                    raise Exception(f"API error: {response.status_code} - {response.text}")
                
                # Parse JSON response
                data = response.json()
                
                # Extract content (Firecrawl returns markdown by default)
                if "data" in data:
                    content = data["data"].get("markdown") or data["data"].get("content") or ""
                else:
                    content = data.get("markdown") or data.get("content") or ""
                
                if not content:
                    raise Exception("Empty content returned from Firecrawl API")
                    
        except httpx.RequestError as e:
            time_taken = time.time() - start_time
            return {
                "tool_name": self.tool_name,
                "time_taken": round(time_taken, 3),
                "content_length": 0,
                "content_snippet": f"ERROR: Network failure - {str(e)}",
                "error": f"Network error: {str(e)}"
            }
        except Exception as e:
            time_taken = time.time() - start_time
            return {
                "tool_name": self.tool_name,
                "time_taken": round(time_taken, 3),
                "content_length": 0,
                "content_snippet": f"ERROR: {str(e)}",
                "error": str(e)
            }
        
        time_taken = time.time() - start_time
        return self.format_output(time_taken, content)


# BENCHMARK RUNNER

async def run_benchmark(url: str, firecrawl_api_key: Optional[str] = None) -> List[Dict]:
    """
    Run all scrapers on the given URL and collect results
    
    Args:
        url: The URL to scrape
        firecrawl_api_key: Optional Firecrawl API key (defaults to env var)
        
    Returns:
        List of result dictionaries from all scrapers
    """
    print(f"\n{'='*70}")
    print(f" Starting Web Scraping Benchmark")
    print(f"{'='*70}")
    print(f"Target URL: {url}\n")
    
    # Instantiate all scrapers
    scrapers = [
        PlaywrightScraper(),
        Crawl4AIScraper(),
        FirecrawlScraper(api_key=firecrawl_api_key)
    ]
    
    results = []
    
    # Run scrapers concurrently for speed
    tasks = [scraper.scrape(url) for scraper in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to error dictionaries
    formatted_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            formatted_results.append({
                "tool_name": scrapers[i].tool_name,
                "time_taken": 0,
                "content_length": 0,
                "content_snippet": f"ERROR: {str(result)}",
                "error": str(result)
            })
        else:
            formatted_results.append(result)
    
    # Print results
    print("\n" + "="*70)
    print(" BENCHMARK RESULTS")
    print("="*70 + "\n")
    
    for result in formatted_results:
        print(f"Tool: {result['tool_name']}")
        print(f"   Time Taken: {result['time_taken']}s")
        print(f"   Content Length: {result['content_length']} characters")
        
        if "error" in result:
            print(f"   Error: {result.get('error', 'Unknown')}")
        else:
            print(f"   Success")
            
        snippet = result['content_snippet']
        if len(snippet) > 100:
            snippet = snippet[:100] + "..."
        print(f"   Snippet: {snippet}")
        print()
    
    # Print summary
    successful = [r for r in formatted_results if "error" not in r]
    if successful:
        fastest = min(successful, key=lambda x: x['time_taken'])
        print(f" Fastest: {fastest['tool_name']} ({fastest['time_taken']}s)")
        
        largest = max(successful, key=lambda x: x['content_length'])
        print(f" Most Content: {largest['tool_name']} ({largest['content_length']} chars)")
    
    print("\n" + "="*70 + "\n")
    
    return formatted_results


# MAIN EXECUTION

async def main():
    """Main entry point for the benchmark"""
    
    # Example URL - replace with your target
    test_url = "https://react.dev/"
    
    
    print("\n Web Scraping Benchmark System")
    print("=" * 70)
    print("\nThis script will benchmark three scraping methods:")
    print("  1. Playwright (Headless Browser)")
    print("  2. Crawl4AI (AI-Powered Crawler)")
    print("  3. Firecrawl (API Service)")
    print()
    
    # Run the benchmark
    results = await run_benchmark(test_url)
    
    # Return results for further processing if needed
    return results


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())


