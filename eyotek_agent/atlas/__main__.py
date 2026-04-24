"""ATLAS CLI dispatcher: python -m atlas <observe|advise|chat|list>"""
import asyncio
import sys


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python -m atlas <observe|advise|chat|list|status>")
        print("\n  observe       son 24h tarama (--hours N ile uzat)")
        print("  advise        observation -> suggestion")
        print("  chat          terminal interaktif diyalog")
        print("  list          bekleyen önerileri listele")
        print("  status        özet istatistik")
        sys.exit(1)

    cmd = sys.argv[1]
    sys.argv.pop(1)  # alt scriptlere arg geçişi için ayır

    if cmd == "observe":
        from atlas.observer import main as obs_main
        asyncio.run(obs_main())
    elif cmd == "advise":
        from atlas.advisor import main as adv_main
        asyncio.run(adv_main())
    elif cmd == "chat":
        from atlas.chat import terminal_chat
        asyncio.run(terminal_chat())
    elif cmd == "list":
        from atlas.chat import cmd_list
        print(asyncio.run(cmd_list("terminal")))
    elif cmd == "status":
        from atlas.chat import cmd_status
        print(asyncio.run(cmd_status("terminal")))
    else:
        print(f"Bilinmeyen komut: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
