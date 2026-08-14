# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/torbenfreise/h2pcontrol/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                 |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/h2pcontrol/controller/\_\_init\_\_.py            |        0 |        0 |        0 |        0 |    100% |           |
| src/h2pcontrol/controller/app.py                     |       20 |       20 |        4 |        0 |      0% |      1-34 |
| src/h2pcontrol/controller/framework/\_\_init\_\_.py  |        0 |        0 |        0 |        0 |    100% |           |
| src/h2pcontrol/controller/framework/experiment.py    |       91 |        3 |       20 |        3 |     95% |51-\>53, 77-78, 137 |
| src/h2pcontrol/controller/framework/parameters.py    |       46 |        2 |       16 |        2 |     94% |    70, 73 |
| src/h2pcontrol/controller/framework/results.py       |       31 |        0 |        0 |        0 |    100% |           |
| src/h2pcontrol/controller/framework/scan.py          |       99 |        0 |       38 |        0 |    100% |           |
| src/h2pcontrol/controller/framework/stubs.py         |        6 |        1 |        0 |        0 |     83% |        17 |
| src/h2pcontrol/controller/framework/views.py         |       89 |        0 |       10 |        0 |    100% |           |
| src/h2pcontrol/controller/runtime/\_\_init\_\_.py    |        0 |        0 |        0 |        0 |    100% |           |
| src/h2pcontrol/controller/runtime/engine.py          |      198 |        7 |       44 |        2 |     96% |118, 123, 317, 324-327 |
| src/h2pcontrol/controller/runtime/events.py          |       52 |        0 |        0 |        0 |    100% |           |
| src/h2pcontrol/controller/runtime/log\_aggregator.py |       94 |        6 |       16 |        3 |     92% |94-96, 120, 126-127, 138-\>141, 141-\>exit, 155-\>152 |
| src/h2pcontrol/controller/runtime/run\_metadata.py   |       14 |        2 |        2 |        0 |     88% |     25-26 |
| src/h2pcontrol/controller/runtime/session.py         |       49 |        5 |        6 |        0 |     91% |     74-78 |
| src/h2pcontrol/controller/runtime/spec.py            |       81 |        3 |        6 |        0 |     97% |69, 84, 93 |
| src/h2pcontrol/controller/runtime/store.py           |      141 |        2 |       48 |        3 |     97% |172, 240-\>exit, 246 |
| src/h2pcontrol/controller/ui/\_\_init\_\_.py         |        0 |        0 |        0 |        0 |    100% |           |
| src/h2pcontrol/controller/ui/engine\_bridge.py       |       30 |        0 |       12 |        1 |     98% | 43-\>exit |
| src/h2pcontrol/controller/ui/experiment\_panel.py    |      301 |       51 |       70 |        6 |     82% |49, 53, 57, 78, 122-124, 249, 256-277, 280-282, 285, 288, 291, 298-304, 307-312, 315, 318, 321, 352, 355, 445 |
| src/h2pcontrol/controller/ui/experiment\_view.py     |       19 |       19 |        0 |        0 |      0% |      1-30 |
| src/h2pcontrol/controller/ui/log\_dock.py            |      189 |        3 |       32 |        4 |     97% |199, 210, 216, 330-\>exit |
| src/h2pcontrol/controller/ui/main\_window.py         |      166 |      166 |       16 |        0 |      0% |     1-235 |
| src/h2pcontrol/controller/ui/plot\_dock.py           |      116 |       13 |       28 |        3 |     85% |85-96, 114, 146-\>143, 173-\>exit |
| src/h2pcontrol/controller/ui/run\_controls.py        |       44 |        0 |        2 |        0 |    100% |           |
| src/h2pcontrol/controller/ui/schedule\_dock.py       |      164 |       19 |       42 |        6 |     85% |48, 112-113, 121, 140-143, 167, 171, 180-\>178, 182-\>178, 202-206, 246-249 |
| src/h2pcontrol/controller/ui/settings\_dialog.py     |       35 |       35 |        2 |        0 |      0% |      1-58 |
| **TOTAL**                                            | **2075** |  **357** |  **414** |   **33** | **83%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/torbenfreise/h2pcontrol/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/torbenfreise/h2pcontrol/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/torbenfreise/h2pcontrol/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/torbenfreise/h2pcontrol/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Ftorbenfreise%2Fh2pcontrol%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/torbenfreise/h2pcontrol/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.